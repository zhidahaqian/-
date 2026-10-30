"""生成真实微调前后回答及人工评分表；不伪造正确率。"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.data_utils import read_jsonl, verify_disjoint
from training.inference import generate, load_model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--model", default=None, help="通常自动读取训练基座；仅迁移同一模型路径时覆盖")
    parser.add_argument("--output-dir", default="outputs/evaluation")
    parser.add_argument("--limit", type=int, default=0, help="0 表示评测全部测试样本")
    parser.add_argument("--max-new-tokens", type=int, default=384)
    parser.add_argument("--quantize", action="store_true")
    args = parser.parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "results.jsonl").exists():
        raise SystemExit("评测结果已存在，请指定新的输出目录以保留旧实验。")
    datasets = [read_jsonl(ROOT / f"data/training/{n}.jsonl") for n in ("train", "validation", "test")]
    verify_disjoint(*datasets)
    tests = datasets[-1][:args.limit] if args.limit > 0 else datasets[-1]
    model, tokenizer, name = load_model(args.adapter, args.model, args.quantize)
    warmup = [{"role": "user", "content": "你好"}]
    generate(model, tokenizer, warmup, 8, False)
    generate(model, tokenizer, warmup, 8, True)
    rows = []
    with (output / "results.jsonl").open("w", encoding="utf-8") as handle:
        for sample in tests:
            responses = {}
            # 交替顺序，减轻缓存和温度变化造成的先后偏差；单次计时仍仅供参考。
            order = [("base", False), ("tuned", True)] if len(rows)%2 == 0 else [("tuned", True), ("base", False)]
            for label, use_adapter in order:
                responses[label] = generate(model, tokenizer, sample["messages"][:-1], args.max_new_tokens, use_adapter)
            row = {"sample_id": sample["id"], "question_id": sample["question_id"], "task": sample["task"],
                   "reference": sample["messages"][-1]["content"],
                   "base_response": responses["base"]["content"], "tuned_response": responses["tuned"]["content"],
                   "base_seconds": responses["base"]["seconds"], "tuned_seconds": responses["tuned"]["seconds"]}
            handle.write(json.dumps(row, ensure_ascii=False)+"\n")
            handle.flush()
            rows.append(row)
            print(f"Evaluated {len(rows)}/{len(tests)}: {sample['id']}")
    with (output / "human_review.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["sample_id", "task", "reference", "base_response", "tuned_response", "base_correct_0_1",
                  "tuned_correct_0_1", "base_clarity_1_5", "tuned_clarity_1_5", "base_hint_leak_0_1", "tuned_hint_leak_0_1", "reviewer_notes"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    adapter_file = Path(args.adapter) / "adapter_model.safetensors"
    metadata = {"base_model": name, "adapter": str(args.adapter), "samples": len(rows),
                "decode": {"do_sample": False, "max_new_tokens": args.max_new_tokens, "enable_thinking": False},
                "same_prompts": True, "quantized": args.quantize,
                "test_sha256": hashlib.sha256((ROOT / "data/training/test.jsonl").read_bytes()).hexdigest(),
                "adapter_sha256": hashlib.sha256(adapter_file.read_bytes()).hexdigest() if adapter_file.exists() else None,
                "note": "人工评分列刻意留空。输入提供参考解析，评估的是辅导行为，不是闭卷解题能力。"}
    (output / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved actual comparisons and blank human review sheet to {output}")


if __name__ == "__main__":
    main()
