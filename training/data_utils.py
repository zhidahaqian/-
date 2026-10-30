"""不依赖 GPU 的数据检查与仅助手回答参与损失的编码逻辑。"""
import json
from pathlib import Path


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_disjoint(*datasets):
    seen = set()
    for rows in datasets:
        families = {row["family"] for row in rows}
        if seen & families:
            raise ValueError("训练、验证、测试集合存在题族交叉，停止训练")
        seen.update(families)


def encode_sample(row, tokenizer, max_length):
    messages = row["messages"]
    if messages[-1]["role"] != "assistant":
        raise ValueError("最后一条消息必须是目标助手回答")
    prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False,
                                           add_generation_prompt=True, enable_thinking=False)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer(messages[-1]["content"] + tokenizer.eos_token, add_special_tokens=False)["input_ids"]
    if len(prompt_ids) + len(answer_ids) > max_length:
        raise ValueError(f"样本 {row['id']} 超过 max-length={max_length}，请检查长度或提高配置；不会静默截断")
    if not answer_ids:
        raise ValueError("助手回答不能为空")
    return {"input_ids": prompt_ids + answer_ids, "attention_mask": [1]*(len(prompt_ids)+len(answer_ids)),
            "labels": [-100]*len(prompt_ids) + answer_ids}
