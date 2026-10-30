"""训练后推理公共代码；评测两组共享同一基座与生成参数。"""
import json
import time
from contextlib import nullcontext
from pathlib import Path


def load_model(adapter=None, model_name=None, quantize=False):
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    if adapter:
        config_path = Path(adapter) / "adapter_config.json"
        if not config_path.exists():
            raise ValueError("找不到 adapter_config.json，请先完成训练并确认适配器路径")
        recorded_base = json.loads(config_path.read_text())["base_model_name_or_path"]
        model_name = model_name or recorded_base
    model_name = model_name or "Qwen/Qwen3-1.7B"
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if device.startswith("cuda") else torch.float32
    if quantize and device == "cpu":
        raise ValueError("本工具的 4-bit 模式要求 CUDA GPU")
    kwargs = dict(torch_dtype=dtype, device_map={"": device}, attn_implementation="sdpa")
    if quantize:
        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                          bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype)
    tokenizer = AutoTokenizer.from_pretrained(adapter or model_name)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_name, **kwargs)
    if adapter:
        model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return model, tokenizer, model_name


def generate(model, tokenizer, messages, max_new_tokens=384, use_adapter=True, max_input_tokens=4096):
    import torch
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    inputs = tokenizer(text, return_tensors="pt", add_special_tokens=False).to(model.device)
    input_length = inputs["input_ids"].shape[-1]
    if input_length > max_input_tokens:
        raise ValueError(f"输入长度超过 {max_input_tokens} tokens，请缩短题目或追问")
    context = model.disable_adapter() if hasattr(model, "disable_adapter") and not use_adapter else nullcontext()
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    started = time.monotonic()
    with context, torch.inference_mode():
        result = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                                pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    seconds = time.monotonic()-started
    new_tokens = result[0][input_length:]
    return {"content": tokenizer.decode(new_tokens, skip_special_tokens=True).strip(),
            "seconds": round(seconds, 4), "input_tokens": input_length, "output_tokens": len(new_tokens)}
