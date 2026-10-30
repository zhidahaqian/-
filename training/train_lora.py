"""单 GPU LoRA / QLoRA SFT，默认 Qwen3-1.7B。请在云 GPU 中执行。"""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.data_utils import encode_sample, read_jsonl, verify_disjoint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="Qwen/Qwen3-1.7B")
    parser.add_argument("--output-dir", default="outputs/lora")
    parser.add_argument("--epochs", type=float, default=3)
    parser.add_argument("--max-steps", type=int, default=-1, help="首次试跑建议 5，输出到独立目录")
    parser.add_argument("--max-length", type=int, default=1536)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--quantize", action="store_true", help="启用 4-bit NF4 QLoRA；默认使用普通 LoRA")
    args = parser.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer, TrainingArguments, set_seed

    if not torch.cuda.is_available():
        raise SystemExit("未检测到 CUDA GPU。本脚本用于云 GPU，不会在本机静默启动耗时的 CPU 训练。")
    output = Path(args.output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit("输出目录非空。请指定新目录，避免覆盖已有训练结果。")
    paths = [ROOT / f"data/training/{name}.jsonl" for name in ("train", "validation", "test")]
    train, validation, test = [read_jsonl(path) for path in paths]
    verify_disjoint(train, validation, test)
    set_seed(42)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    encoded_train = [encode_sample(row, tokenizer, args.max_length) for row in train]
    encoded_val = [encode_sample(row, tokenizer, args.max_length) for row in validation]
    print(f"train={len(train)}, validation={len(validation)}, max_tokens={max(len(x['input_ids']) for x in encoded_train + encoded_val)}")
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    kwargs = dict(torch_dtype=dtype, device_map={"": 0}, attn_implementation="sdpa")
    if args.quantize:
        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                          bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype)
    model = AutoModelForCausalLM.from_pretrained(args.model, **kwargs)
    if args.quantize:
        model = prepare_model_for_kbit_training(model)
    model.config.use_cache = False
    model = get_peft_model(model, LoraConfig(r=args.rank, lora_alpha=args.rank*2, lora_dropout=0.05,
                                            target_modules="all-linear", bias="none", task_type="CAUSAL_LM"))
    model.enable_input_require_grads()
    model.print_trainable_parameters()

    def collate(rows):
        width = max(len(row["input_ids"]) for row in rows)
        return {key: torch.tensor([row[key] + [pad]*(width-len(row[key])) for row in rows], dtype=torch.long)
                for key, pad in (("input_ids", tokenizer.pad_token_id), ("attention_mask", 0), ("labels", -100))}

    output.mkdir(parents=True)
    training_args = TrainingArguments(output_dir=str(output), num_train_epochs=args.epochs,
        max_steps=args.max_steps, per_device_train_batch_size=args.batch_size, per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation, learning_rate=args.learning_rate,
        warmup_ratio=0.1, lr_scheduler_type="cosine", weight_decay=0.01,
        logging_steps=1, eval_strategy="epoch", save_strategy="epoch", save_total_limit=2,
        load_best_model_at_end=True, metric_for_best_model="eval_loss", greater_is_better=False,
        bf16=dtype == torch.bfloat16, fp16=dtype == torch.float16,
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        optim="adamw_torch", report_to="none", seed=42, data_seed=42)
    trainer = Trainer(model=model, args=training_args, train_dataset=encoded_train,
                      eval_dataset=encoded_val, data_collator=collate)
    started = time.monotonic()
    result = trainer.train()
    metrics = trainer.evaluate()
    trainer.save_model(str(output))
    tokenizer.save_pretrained(output)
    trainer.save_state()
    metadata = {"base_model": args.model, "args": vars(args), "seed": 42,
                "seconds": time.monotonic()-started, "gpu": torch.cuda.get_device_name(0),
                "peak_allocated_gb": torch.cuda.max_memory_allocated()/1024**3,
                "train_metrics": result.metrics, "validation_metrics": metrics,
                "dataset_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                "python": platform.python_version(),
                "packages": {p: importlib.metadata.version(p) for p in ["torch", "transformers", "peft", "accelerate"]},
                "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
                "total_parameters": sum(p.numel() for p in model.parameters()),
                "note": "真实训练记录；测试集未参与训练或最优检查点选择。小样本实验不保证泛化提升。"}
    (output / "run_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "loss_history.json").write_text(json.dumps(trainer.state.log_history, indent=2), encoding="utf-8")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        logs = trainer.state.log_history
        for key, label in [("loss", "Training loss"), ("eval_loss", "Validation loss")]:
            points = [row for row in logs if key in row]
            if points:
                plt.plot([p["step"] for p in points], [p[key] for p in points], marker=".", label=label)
        plt.xlabel("Optimizer step")
        plt.ylabel("Loss")
        plt.legend()
        plt.tight_layout()
        plt.savefig(output / "loss.png", dpi=160)
        plt.close()
    except ImportError:
        print("matplotlib 不可用，原始损失数据已经保存。")
    print(f"Training finished. Adapter and actual logs: {output}")


if __name__ == "__main__":
    main()
