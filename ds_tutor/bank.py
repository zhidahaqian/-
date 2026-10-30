import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAPTERS = ["线性表", "栈与队列", "树与二叉树", "图", "查找", "排序"]


def load_questions(path=None):
    questions = json.loads(Path(path or ROOT / "data/questions.json").read_text(encoding="utf-8"))
    seen = set()
    for q in questions:
        if q["id"] in seen or q["answer"] not in q["options"]:
            raise ValueError("题库包含重复 ID 或无效答案")
        if len(q["options"]) != 4 or not all(q.get(k) for k in ("hint", "explanation", "family", "stem")):
            raise ValueError("题库字段不完整")
        seen.add(q["id"])
    return questions


def filter_questions(questions, chapter="全部章节", difficulty="全部难度", search=""):
    return [q for q in questions
            if (chapter == "全部章节" or q["chapter"] == chapter)
            and (difficulty == "全部难度" or q["difficulty"] == difficulty)
            and (not search or search.casefold() in (q["stem"] + q["topic"]).casefold())]


def grade(question, answer):
    if answer not in question["options"]:
        raise ValueError("请提交有效选项")
    return answer == question["answer"]
