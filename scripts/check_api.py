"""发起一条真实辅导请求；只保存公开题目、回答和脱敏元信息。"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ds_tutor.bank import load_questions
from ds_tutor.llm import ModelError, complete, settings_for
from ds_tutor.prompts import make_messages


def main():
    question = next(q for q in load_questions() if q["id"] == "DS017")
    settings = settings_for("云端 API")
    settings.max_tokens = 384
    settings.timeout = 45
    try:
        result = complete(make_messages(question, "explain", "A"), settings)
    except ModelError as error:
        print(str(error))
        return 1
    evidence = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "question_id": question["id"],
                "question": question["stem"], "student_answer": "A", "expected_answer": question["answer"],
                "configured_model": settings.model, "result": result,
                "note": "真实 API 连通性样例；不代表微调实验，也不能单凭返回名称核实服务商底层模型身份。"}
    output = ROOT / "runtime/api_smoke.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
