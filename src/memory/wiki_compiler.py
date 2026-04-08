"""LLM-powered wiki compiler — distills raw docs into high-density wiki pages."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.core.bus import EventBus
from src.core.provider import _httpx_chat, get_provider_client, PROVIDERS
from src.memory.wiki import WikiPage, WikiStore
from src.promptos.engine import PromptOS

_RAW_ROOT = Path(__file__).resolve().parent.parent.parent / "raw"
_WIKI_ROOT = Path(__file__).resolve().parent.parent.parent / "wiki"
_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "wiki.db"

_COMPILE_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS compile_meta (
    path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    compiled_at REAL NOT NULL
);
"""


@dataclass
class CompileResult:
    compiled: int = 0
    skipped: int = 0
    errors: int = 0
    pages_written: list[str] = field(default_factory=list)


class WikiCompiler:
    """Reads raw docs, assembles a Librarian prompt, distills via LLM, writes wiki pages."""

    def __init__(
        self,
        bus: EventBus,
        prompt_os: PromptOS,
        wiki_store: Optional[WikiStore] = None,
    ) -> None:
        self.bus = bus
        self.os = prompt_os
        self.wiki_store = wiki_store or WikiStore()
        self._init_meta_db()

    def _init_meta_db(self) -> None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH))
        conn.executescript(_COMPILE_META_SCHEMA)
        conn.close()

    def _get_meta_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    async def compile_resource(
        self, source_path: str, category: str = "General"
    ) -> CompileResult:
        """Compile a single raw file into a wiki page."""
        result = CompileResult()
        path = Path(source_path)

        if not path.exists():
            result.errors += 1
            return result

        content = path.read_text(encoding="utf-8")
        content_hash = hashlib.md5(content.encode()).hexdigest()

        # Incremental: skip if unchanged
        if self._is_unchanged(str(path), content_hash):
            result.skipped += 1
            return result

        # Derive category from path if default
        if category == "General":
            category = self._derive_category(path)

        title = path.stem.replace("_", " ").title()

        # Truncate large files to fit LLM context window (~8K chars)
        max_raw_chars = 8000
        raw_for_llm = content[:max_raw_chars]
        if len(content) > max_raw_chars:
            raw_for_llm += "\n\n[... truncated from {} total chars ...]".format(
                len(content)
            )

        # Assemble Librarian prompt
        try:
            prompt = await self.os.assemble_librarian(
                raw_content=raw_for_llm, category=category, title=title
            )
            distilled = await self._call_llm(prompt)
        except Exception as exc:
            # Fallback: use raw content if LLM unavailable
            print(f"[wiki_compiler] LLM failed for {path.name}: {exc}")
            distilled = content

        # Write to wiki store
        page = WikiPage(
            title=title,
            category=category,
            summary=self._extract_summary(distilled),
            content=distilled,
            tags=self._extract_tags(distilled, category),
        )
        self.wiki_store.put(page)

        # Write to filesystem too
        target = self._target_path(str(path))
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(distilled, encoding="utf-8")

        # Record compilation
        self._record_compile(str(path), content_hash)

        result.compiled += 1
        result.pages_written.append(str(target))

        # Update index
        self._ensure_index(category)

        return result

    async def compile_directory(
        self,
        raw_dir: Path,
        category: str = "General",
        limit: int = 0,
        category_filter: str = "",
    ) -> CompileResult:
        """Batch compile all .md/.rst/.txt files in a directory.

        Args:
            raw_dir: Root directory to scan.
            category: Default category for compiled pages.
            limit: Max files to process (0 = unlimited).
            category_filter: Only process files under this subdirectory (e.g. "classes").
        """
        result = CompileResult()
        raw = Path(raw_dir)

        if not raw.exists():
            return result

        scan_dir = raw / category_filter if category_filter else raw

        for path in sorted(scan_dir.rglob("*")):
            if limit and result.compiled + result.skipped + result.errors >= limit:
                break
            if path.suffix in (".md", ".rst", ".txt"):
                file_result = await self.compile_resource(str(path), category)
                result.compiled += file_result.compiled
                result.skipped += file_result.skipped
                result.errors += file_result.errors
                result.pages_written.extend(file_result.pages_written)

        return result

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM to produce distilled wiki page content via nvidia provider."""
        import os

        profile = PROVIDERS["nvidia"]
        api_key = os.getenv("LLM_API_KEY", "") or os.getenv("NVIDIA_API_KEY", "")
        base_url = os.getenv("LLM_BASE_URL", "") or profile["base_url"]
        model = "google/gemma-4-31b-it"

        return await asyncio.wait_for(
            _httpx_chat(
                base_url=base_url,
                api_key=api_key,
                model=model,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=300,
        )

    def _target_path(self, source_path: str) -> str:
        """raw/godot/tutorials/foo.rst -> wiki/godot/tutorials/foo.md"""
        src = Path(source_path)
        try:
            relative = src.relative_to(_RAW_ROOT)
        except ValueError:
            # Try matching by suffix after 'raw/' for relative paths
            parts = src.parts
            for i, part in enumerate(parts):
                if part == "raw" and i + 1 < len(parts):
                    relative = Path(*parts[i + 1:])
                    break
            else:
                relative = Path(src.name)
        target = _WIKI_ROOT / relative.with_suffix(".md")
        return str(target)

    def _derive_category(self, path: Path) -> str:
        """Derive category from raw file path, e.g. raw/godot/classes/... -> Godot."""
        parts = path.parts
        # Look for 'godot' in path
        for part in parts:
            if part.lower() == "godot":
                return "Godot"
        return "General"

    def _extract_summary(self, content: str) -> str:
        """Extract first non-empty paragraph as summary."""
        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and len(stripped) > 10:
                return stripped[:200]
        return content[:200]

    def _extract_tags(self, content: str, category: str) -> list[str]:
        """Extract [[CrossLink]] tags from content."""
        import re

        tags = [category.lower()]
        crosslinks = re.findall(r"\[\[(\w+)\]\]", content)
        tags.extend(crosslinks[:5])
        return tags

    def _is_unchanged(self, path: str, content_hash: str) -> bool:
        """Check if file was already compiled with same content hash."""
        conn = self._get_meta_conn()
        row = conn.execute(
            "SELECT content_hash FROM compile_meta WHERE path = ?", (path,)
        ).fetchone()
        conn.close()
        return row is not None and row["content_hash"] == content_hash

    def _record_compile(self, path: str, content_hash: str) -> None:
        """Record a successful compilation."""
        conn = self._get_meta_conn()
        conn.execute(
            """INSERT OR REPLACE INTO compile_meta (path, content_hash, compiled_at)
               VALUES (?, ?, ?)""",
            (path, content_hash, time.time()),
        )
        conn.commit()
        conn.close()

    def _ensure_index(self, category: str) -> None:
        """Create/update wiki/<category>/index.md with links to all compiled pages."""
        pages = self.wiki_store.get_by_category(category)
        if not pages:
            return

        lines = [f"# {category} Wiki Index\n"]
        for page in sorted(pages, key=lambda p: p.title):
            filename = page.title.lower().replace(" ", "_")
            lines.append(f"- [[{page.title}]] — {page.summary[:80]}")

        index_path = _WIKI_ROOT / category.lower() / "index.md"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("\n".join(lines), encoding="utf-8")
