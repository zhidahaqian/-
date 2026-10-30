"""按章节分层、按题族划分；同题的四种辅导样本绝不跨集合。"""
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ds_tutor.bank import CHAPTERS, load_questions
from ds_tutor.prompts import make_messages


def make_samples(q):
    wrong = next(key for key in q["options"] if key != q["answer"])
    explanation = f"结论：正确答案是 {q['answer']}，{q['options'][q['answer']]}。\n解题步骤：{q['explanation']}\n易错提醒：{q['misconception']}"
    specs = [
        ("hint", None, "", q["hint"]),
        ("explain", q["answer"], "", "结论：你的选项正确。" + explanation.removeprefix("结论：")),
        ("explain", wrong, "", f"结论：你选择了 {wrong}，这与标准答案不符。" + explanation.removeprefix("结论：")),
        ("followup", wrong, "这道题最容易混淆的知识点是什么？", f"本题容易出现的误解是：{q['misconception']}\n{q['explanation']}"),
    ]
    return [{"id": f"{q['id']}-{i}", "question_id": q["id"], "family": q["family"],
             "task": task, "expected_answer": q["answer"],
             "messages": make_messages(q, task, answer, followup) + [{"role": "assistant", "content": target}]}
            for i, (task, answer, followup, target) in enumerate(specs)]


def build_splits(questions, seed=42):
    rng = random.Random(seed)
    splits = {name: [] for name in ("train", "validation", "test")}
    for chapter in CHAPTERS:
        groups = defaultdict(list)
        for q in questions:
            if q["chapter"] == chapter:
                groups[q["family"]].append(q)
        families = sorted(groups)
        if len(families) < 3:
            raise ValueError(f"{chapter} 至少需要三个独立题族")
        rng.shuffle(families)
        heldout = max(1, len(families)//5)
        for i, family in enumerate(families):
            name = "test" if i < heldout else "validation" if i < 2*heldout else "train"
            for q in groups[family]:
                splits[name].extend(make_samples(q))
    return splits


def main():
    output = ROOT / "data/training"
    output.mkdir(parents=True, exist_ok=True)
    splits = build_splits(load_questions())
    manifest = {"seed": 42, "provenance": "本项目自编题库，经固定模板生成辅导样本；尚待教师复核。",
                "purpose": "给定参考资料的辅导行为微调；不是闭卷知识能力基准。",
                "question_bank_sha256": hashlib.sha256((ROOT / "data/questions.json").read_bytes()).hexdigest(),
                "splits": {}}
    for name, rows in splits.items():
        content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        (output / f"{name}.jsonl").write_text(content, encoding="utf-8")
        manifest["splits"][name] = {"samples": len(rows), "questions": len({r['question_id'] for r in rows}),
                                     "sha256": hashlib.sha256(content.encode()).hexdigest(),
                                     "question_ids": sorted({r['question_id'] for r in rows})}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: value["samples"] for name, value in manifest["splits"].items()}))


if __name__ == "__main__":
    main()
