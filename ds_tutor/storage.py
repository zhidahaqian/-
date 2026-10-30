import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv("APP_DB_PATH", ROOT / "runtime/study.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS attempts (
                id TEXT PRIMARY KEY, learner TEXT NOT NULL, qid TEXT NOT NULL,
                answer TEXT NOT NULL, correct INTEGER NOT NULL,
                created_at TEXT NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS by_learner ON attempts(learner, created_at)")

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, learner, qid, answer, correct, event_id):
        with self.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO attempts VALUES (?, ?, ?, ?, ?, ?)",
                         (event_id, learner, qid, answer, int(correct), datetime.now(timezone.utc).isoformat()))

    def records(self, learner):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM attempts WHERE learner=? ORDER BY created_at DESC, rowid DESC", (learner,))]

    def export(self, learner):
        rows = self.records(learner)
        for row in rows:
            row.pop("learner", None)
        return json.dumps(rows, ensure_ascii=False, indent=2)


def local_learner():
    path = ROOT / "runtime/local_profile.json"
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["id"]
    value = uuid.uuid4().hex
    path.write_text(json.dumps({"id": value}), encoding="utf-8")
    return value


def summarize(records):
    latest = {}
    ever_wrong = set()
    for row in records:
        latest.setdefault(row["qid"], row)
        if not row["correct"]:
            ever_wrong.add(row["qid"])
    return {"attempts": len(records), "correct": sum(r["correct"] for r in records),
            "unique": len(latest), "latest": latest, "ever_wrong": ever_wrong,
            "pending": {qid for qid in ever_wrong if not latest[qid]["correct"]}}
