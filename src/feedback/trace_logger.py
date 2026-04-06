import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "traces.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_traces (
    trace_id TEXT PRIMARY KEY,
    session_id TEXT,
    timestamp REAL,
    policy_decision TEXT,
    memory_retrieved TEXT,
    prompt_template TEXT,
    tool_calls TEXT,
    cost_estimate REAL,
    actual_cost REAL,
    outcome TEXT,
    user_feedback TEXT
);

CREATE INDEX IF NOT EXISTS idx_traces_session ON decision_traces(session_id);
CREATE INDEX IF NOT EXISTS idx_traces_outcome ON decision_traces(outcome);
"""


@dataclass
class DecisionTrace:
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)
    policy_decision: dict = field(default_factory=dict)
    memory_retrieved: list = field(default_factory=list)
    prompt_template: str = ""
    tool_calls: list = field(default_factory=list)
    cost_estimate: float = 0.0
    actual_cost: float = 0.0
    outcome: str = ""
    user_feedback: str = ""


class TraceLogger:
    """SQLite-backed logger for decision traces."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(_SCHEMA)

    def record(self, trace: DecisionTrace) -> None:
        self._conn.execute(
            """INSERT INTO decision_traces
               (trace_id, session_id, timestamp, policy_decision, memory_retrieved,
                prompt_template, tool_calls, cost_estimate, actual_cost, outcome, user_feedback)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace.trace_id,
                trace.session_id,
                trace.timestamp,
                json.dumps(trace.policy_decision),
                json.dumps(trace.memory_retrieved),
                trace.prompt_template,
                json.dumps(trace.tool_calls),
                trace.cost_estimate,
                trace.actual_cost,
                trace.outcome,
                trace.user_feedback,
            ),
        )
        self._conn.commit()

    def get_by_session(self, session_id: str) -> List[DecisionTrace]:
        rows = self._conn.execute(
            "SELECT * FROM decision_traces WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [self._row_to_trace(r) for r in rows]

    def get_by_outcome(self, outcome: str, limit: int = 50) -> List[DecisionTrace]:
        rows = self._conn.execute(
            "SELECT * FROM decision_traces WHERE outcome = ? ORDER BY timestamp DESC LIMIT ?",
            (outcome, limit),
        ).fetchall()
        return [self._row_to_trace(r) for r in rows]

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM decision_traces").fetchone()
        return row[0]

    def _row_to_trace(self, row: tuple) -> DecisionTrace:
        return DecisionTrace(
            trace_id=row[0],
            session_id=row[1],
            timestamp=row[2],
            policy_decision=json.loads(row[3]) if row[3] else {},
            memory_retrieved=json.loads(row[4]) if row[4] else [],
            prompt_template=row[5] or "",
            tool_calls=json.loads(row[6]) if row[6] else [],
            cost_estimate=row[7] or 0.0,
            actual_cost=row[8] or 0.0,
            outcome=row[9] or "",
            user_feedback=row[10] or "",
        )

    def close(self) -> None:
        self._conn.close()
