"""SQLite-backed wiki store for structured knowledge pages."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "wiki.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wiki_pages (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    created_at REAL,
    updated_at REAL
);

CREATE INDEX IF NOT EXISTS idx_wiki_category ON wiki_pages(category);
"""


@dataclass
class WikiPage:
    title: str
    category: str
    summary: str
    content: str = ""
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "category": self.category,
            "summary": self.summary,
            "content": self.content,
            "tags": self.tags,
        }


class WikiStore:
    """SQLite-backed CRUD for wiki/knowledge pages."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(_SCHEMA)

    def put(self, page: WikiPage) -> None:
        import time

        now = time.time()
        self._conn.execute(
            """INSERT OR REPLACE INTO wiki_pages
               (id, title, category, summary, content, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                page.id,
                page.title,
                page.category,
                page.summary,
                page.content,
                json.dumps(page.tags),
                now,
                now,
            ),
        )
        self._conn.commit()

    def get_index(self) -> Dict[str, List[dict]]:
        """Return pages grouped by category: {category: [{title, summary}, ...]}"""
        rows = self._conn.execute(
            "SELECT title, category, summary FROM wiki_pages ORDER BY category, title"
        ).fetchall()
        index: Dict[str, List[dict]] = {}
        for title, category, summary in rows:
            index.setdefault(category, []).append({"title": title, "summary": summary})
        return index

    def get_by_category(self, category: str) -> List[WikiPage]:
        rows = self._conn.execute(
            "SELECT * FROM wiki_pages WHERE category = ? ORDER BY title",
            (category,),
        ).fetchall()
        return [self._row_to_page(r) for r in rows]

    def search(self, query: str, limit: int = 20) -> List[WikiPage]:
        rows = self._conn.execute(
            "SELECT * FROM wiki_pages WHERE title LIKE ? OR summary LIKE ? OR content LIKE ? LIMIT ?",
            (f"%{query}%", f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        return [self._row_to_page(r) for r in rows]

    def _row_to_page(self, row: tuple) -> WikiPage:
        return WikiPage(
            id=row[0],
            title=row[1],
            category=row[2],
            summary=row[3],
            content=row[4] or "",
            tags=json.loads(row[5]) if isinstance(row[5], str) else row[5],
        )

    def close(self) -> None:
        self._conn.close()
