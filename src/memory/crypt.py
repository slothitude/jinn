"""The Crypt — SQLite store for deceased JINN worker records and their lessons."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "crypt.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS crypt (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    provider TEXT DEFAULT '',
    born_at REAL NOT NULL,
    died_at REAL,
    task_summary TEXT DEFAULT '',
    tools_used TEXT DEFAULT '[]',
    outcome TEXT DEFAULT '',
    lessons TEXT DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_crypt_died ON crypt(died_at);
CREATE INDEX IF NOT EXISTS idx_crypt_name ON crypt(name);
"""


@dataclass
class CryptEntry:
    name: str
    role: str
    born_at: float
    provider: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    died_at: Optional[float] = None
    task_summary: str = ""
    tools_used: list[str] = field(default_factory=list)
    outcome: str = ""
    lessons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "provider": self.provider,
            "born_at": self.born_at,
            "died_at": self.died_at,
            "task_summary": self.task_summary,
            "tools_used": self.tools_used,
            "outcome": self.outcome,
            "lessons": self.lessons,
        }


class CryptStore:
    """SQLite-backed store for deceased worker records."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(_SCHEMA)

    def put(self, entry: CryptEntry) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO crypt
               (id, name, role, provider, born_at, died_at, task_summary, tools_used, outcome, lessons)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.name,
                entry.role,
                entry.provider,
                entry.born_at,
                entry.died_at or time.time(),
                entry.task_summary,
                json.dumps(entry.tools_used),
                entry.outcome,
                json.dumps(entry.lessons),
            ),
        )
        self._conn.commit()

    def get_by_name(self, name: str) -> List[CryptEntry]:
        rows = self._conn.execute(
            "SELECT * FROM crypt WHERE name = ? ORDER BY died_at DESC",
            (name,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_all(self, limit: int = 100) -> List[CryptEntry]:
        rows = self._conn.execute(
            "SELECT * FROM crypt ORDER BY died_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def get_recent_lessons(self, limit: int = 20) -> List[str]:
        """Return most recent lessons, ordered by died_at DESC."""
        rows = self._conn.execute(
            "SELECT lessons FROM crypt WHERE lessons != '[]' ORDER BY died_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        lessons: list[str] = []
        for (raw,) in rows:
            for lesson in json.loads(raw):
                if lesson not in lessons:
                    lessons.append(lesson)
        return lessons[:limit]

    def search_lessons(self, query: str, limit: int = 20) -> List[str]:
        """Relevance-ranked lesson retrieval — keyword overlap scoring."""
        if not query:
            return self.get_recent_lessons(limit)

        query_words = set(query.lower().split())
        rows = self._conn.execute(
            "SELECT task_summary, lessons FROM crypt WHERE lessons != '[]'"
        ).fetchall()

        scored: list[tuple[float, str]] = []
        seen: set[str] = set()

        for task_summary, raw_lessons in rows:
            # Score based on keyword overlap with task summary
            summary_words = set(task_summary.lower().split())
            overlap = len(query_words & summary_words)
            score = min(overlap / max(len(query_words), 1), 1.0)

            for lesson in json.loads(raw_lessons):
                # Also score lesson text itself
                lesson_words = set(lesson.lower().split())
                lesson_overlap = len(query_words & lesson_words)
                lesson_score = min(lesson_overlap / max(len(query_words), 1), 1.0)
                final_score = max(score, lesson_score)

                if lesson not in seen and final_score > 0:
                    seen.add(lesson)
                    scored.append((final_score, lesson))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [lesson for _, lesson in scored[:limit]]

    def _row_to_entry(self, row: tuple) -> CryptEntry:
        return CryptEntry(
            id=row[0],
            name=row[1],
            role=row[2],
            provider=row[3] or "",
            born_at=row[4],
            died_at=row[5],
            task_summary=row[6] or "",
            tools_used=json.loads(row[7]) if isinstance(row[7], str) else row[7],
            outcome=row[8] or "",
            lessons=json.loads(row[9]) if isinstance(row[9], str) else row[9],
        )

    def close(self) -> None:
        self._conn.close()
