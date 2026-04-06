import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from src.memory.schema import MemoryUnit

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "memory.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    embedding BLOB,
    tags TEXT NOT NULL,
    importance REAL DEFAULT 0.5,
    last_used REAL,
    prompt_fragment TEXT,
    created_at REAL,
    access_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories(tags);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_last_used ON memories(last_used DESC);
"""


class MemoryStore:
    """SQLite-backed CRUD for MemoryUnit records."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def put(self, memory: MemoryUnit) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO memories
               (id, summary, tags, importance, last_used, prompt_fragment, created_at, access_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memory.id,
                memory.summary,
                json.dumps(memory.tags),
                memory.importance,
                memory.last_used,
                memory.prompt_fragment,
                memory.created_at,
                memory.access_count,
            ),
        )
        self._conn.commit()

    def get(self, memory_id: str) -> Optional[MemoryUnit]:
        row = self._conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row:
            return MemoryUnit.from_row(dict(row))
        return None

    def get_all(self, limit: int = 1000) -> List[MemoryUnit]:
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY importance DESC LIMIT ?", (limit,)
        ).fetchall()
        return [MemoryUnit.from_row(dict(r)) for r in rows]

    def search_by_tag(self, tag: str, limit: int = 50) -> List[MemoryUnit]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE tags LIKE ? ORDER BY importance DESC LIMIT ?",
            (f'%"{tag}"%', limit),
        ).fetchall()
        return [MemoryUnit.from_row(dict(r)) for r in rows]

    def delete(self, memory_id: str) -> None:
        self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()

    def update_access(self, memory_id: str) -> None:
        import time

        self._conn.execute(
            "UPDATE memories SET access_count = access_count + 1, last_used = ? WHERE id = ?",
            (time.time(), memory_id),
        )
        self._conn.commit()

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) as cnt FROM memories").fetchone()
        return row["cnt"]

    def close(self) -> None:
        self._conn.close()
