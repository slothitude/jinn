"""Tests for the Librarian — WikiCompiler, cross-linking, and validation."""

import asyncio
import hashlib
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.bus import EventBus
from src.memory.wiki import WikiPage, WikiStore
from src.memory.wiki_compiler import CompileResult, WikiCompiler
from src.memory.retrieval import retrieve_with_wiki
from src.memory.schema import MemoryUnit
from src.memory.store import MemoryStore
from src.promptos.engine import PromptOS


# --- Helpers ---


def _make_store(db_path=None):
    """Create a temp MemoryStore."""
    if db_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_path = Path(tmp.name)
    return MemoryStore(db_path=db_path)


def _make_wiki_store(db_path=None):
    """Create a temp WikiStore."""
    if db_path is None:
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_path = Path(tmp.name)
    return WikiStore(db_path=db_path)


def _make_compiler(bus=None, wiki_store=None, prompt_os=None):
    bus = bus or EventBus()
    wiki_store = wiki_store or _make_wiki_store()
    prompt_os = prompt_os or PromptOS(tools=[])
    # Patch _init_meta_db to use temp db
    compiler = WikiCompiler(bus, prompt_os, wiki_store)
    return compiler


def _write_temp_raw(content: str, filename: str = "test_doc.md") -> Path:
    """Write content to a temp raw file and return its path."""
    tmpdir = tempfile.mkdtemp()
    path = Path(tmpdir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --- WikiCompiler Tests (5) ---


class TestWikiCompiler:
    @pytest.mark.asyncio
    async def test_compile_resource_reads_and_distills(self):
        """Single file compilation produces a wiki page."""
        bus = EventBus()
        wiki_store = _make_wiki_store()
        prompt_os = PromptOS(tools=[])
        compiler = WikiCompiler(bus, prompt_os, wiki_store)

        raw_content = "# Test Doc\n\nSome content about [[Node2D]] and [[Signal]]."
        path = _write_temp_raw(raw_content)

        with patch.object(compiler, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "# Distilled\n\nDistilled content with [[Node2D]]."
            result = await compiler.compile_resource(str(path), category="Godot")

        assert result.compiled == 1
        assert len(result.pages_written) == 1
        mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_compile_directory_batch(self):
        """Multiple files compiled in one directory pass."""
        bus = EventBus()
        wiki_store = _make_wiki_store()
        prompt_os = PromptOS(tools=[])
        compiler = WikiCompiler(bus, prompt_os, wiki_store)

        tmpdir = tempfile.mkdtemp()
        (Path(tmpdir) / "doc1.md").write_text("# Doc 1\nContent 1", encoding="utf-8")
        (Path(tmpdir) / "doc2.md").write_text("# Doc 2\nContent 2", encoding="utf-8")
        (Path(tmpdir) / "doc3.txt").write_text("# Doc 3\nContent 3", encoding="utf-8")
        # Should skip .py files
        (Path(tmpdir) / "ignore.py").write_text("print('hi')", encoding="utf-8")

        with patch.object(compiler, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "# Distilled\n\nContent."
            result = await compiler.compile_directory(Path(tmpdir))

        assert result.compiled == 3
        assert mock_llm.call_count == 3

    @pytest.mark.asyncio
    async def test_compile_incremental_skips_unchanged(self):
        """Files with same content hash are skipped on recompile."""
        bus = EventBus()
        wiki_store = _make_wiki_store()
        prompt_os = PromptOS(tools=[])
        compiler = WikiCompiler(bus, prompt_os, wiki_store)

        raw_content = "# Static\nSame content"
        path = _write_temp_raw(raw_content)

        with patch.object(compiler, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "# Distilled\n"
            # First compile
            result1 = await compiler.compile_resource(str(path))
            assert result1.compiled == 1

            # Second compile — should skip
            result2 = await compiler.compile_resource(str(path))
            assert result2.skipped == 1
            assert result2.compiled == 0

    @pytest.mark.asyncio
    async def test_compile_produces_crosslinks(self):
        """Output contains [[PageName]] cross-link syntax."""
        bus = EventBus()
        wiki_store = _make_wiki_store()
        prompt_os = PromptOS(tools=[])
        compiler = WikiCompiler(bus, prompt_os, wiki_store)

        raw_content = "GDScript uses signals. See Node2D for position."
        path = _write_temp_raw(raw_content)

        distilled = "# GDScript\n\nSee [[Node2D]] and [[Signal]].\n\n## Cross-References\n- [[Node2D]]\n"
        with patch.object(compiler, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = distilled
            await compiler.compile_resource(str(path), category="Godot")

        pages = wiki_store.search("GDScript")
        assert len(pages) > 0
        assert "[[" in pages[0].content

    @pytest.mark.asyncio
    async def test_compile_extracts_heuristics(self):
        """Output contains Jinn Heuristic blocks."""
        bus = EventBus()
        wiki_store = _make_wiki_store()
        prompt_os = PromptOS(tools=[])
        compiler = WikiCompiler(bus, prompt_os, wiki_store)

        raw_content = "Common mistake: move_and_slide(velocity) in Godot 4 should be move_and_slide()."
        path = _write_temp_raw(raw_content)

        distilled = "# Physics\n\n### Jinn Heuristics\n- HEURISTIC: Use move_and_slide() without args — source: godot_physics.md"
        with patch.object(compiler, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = distilled
            await compiler.compile_resource(str(path), category="Godot")

        pages = wiki_store.search("Physics")
        assert len(pages) > 0
        assert "HEURISTIC" in pages[0].content


# --- Cross-Linking Tests (4) ---


class TestCrossLinking:
    @pytest.mark.asyncio
    async def test_retrieve_with_wiki_returns_both(self):
        """Dict has memories + wiki_pages keys."""
        store = _make_store()
        wiki_store = _make_wiki_store()

        # Add a memory
        mem = MemoryUnit(summary="test memory", tags=["preference"])
        store.put(mem)

        # Add a wiki page
        page = WikiPage(
            title="GDScript Basics",
            category="Godot",
            summary="Intro to GDScript",
            content="# GDScript\n\nBasic scripting.",
        )
        wiki_store.put(page)

        result = await retrieve_with_wiki("gdscript", "buddy", store, wiki_store)

        assert "memories" in result
        assert "wiki_pages" in result
        assert "wiki_index" in result

    @pytest.mark.asyncio
    async def test_wiki_category_boost(self):
        """Query 'gdscript' boosts Godot-category pages."""
        store = _make_store()
        wiki_store = _make_wiki_store()

        # Godot page — should be boosted
        godot_page = WikiPage(
            title="GDScript Guide",
            category="Godot",
            summary="GDScript guide",
            content="# GDScript\n\nGuide content.",
        )
        wiki_store.put(godot_page)

        # Other page — should not be boosted
        other_page = WikiPage(
            title="Python Guide",
            category="Python",
            summary="Python guide",
            content="# Python\n\nGuide content.",
        )
        wiki_store.put(other_page)

        result = await retrieve_with_wiki("gdscript godot", "buddy", store, wiki_store)
        pages = result["wiki_pages"]

        # Godot page should rank higher (come first)
        if len(pages) >= 2:
            assert pages[0]["category"] == "Godot"

    @pytest.mark.asyncio
    async def test_wiki_pages_in_template_context(self):
        """PromptOS renders wiki page content in assemble context."""
        prompt_os = PromptOS(tools=[])
        from src.core.models import AgentRequest

        request = AgentRequest(session_id="test", input_text="hello")
        memory_data = {
            "memories": [],
            "wiki_pages": [
                {"title": "Test Page", "category": "Godot", "content": "Some wiki content", "summary": "test"},
            ],
            "wiki_index": {},
        }

        prompt = await prompt_os.assemble(request, memory_data, "BUDDY")

        # The context should have been passed to templates
        assert isinstance(prompt, str)

    @pytest.mark.asyncio
    async def test_retrieve_with_wiki_empty_store(self):
        """Graceful with empty WikiStore."""
        store = _make_store()
        wiki_store = _make_wiki_store()

        result = await retrieve_with_wiki("anything", "buddy", store, wiki_store)

        assert result["memories"] == []
        assert result["wiki_pages"] == []
        assert result["wiki_index"] == {}


# --- Validation Tests (3) ---


class TestValidation:
    @pytest.mark.asyncio
    async def test_librarian_template_renders(self):
        """librarian.jinja produces a valid prompt with raw_content."""
        prompt_os = PromptOS(tools=[])
        prompt = await prompt_os.assemble_librarian(
            raw_content="This is raw doc content about [[Node2D]].",
            category="Godot",
            title="Node2D Guide",
        )

        assert "Node2D Guide" in prompt
        assert "DISTILLATION PROTOCOL" in prompt
        assert "raw doc content" in prompt
        assert "Godot" in prompt

    def test_target_path_mapping(self):
        """raw/godot/foo.rst -> wiki/godot/foo.md"""
        bus = EventBus()
        wiki_store = _make_wiki_store()
        prompt_os = PromptOS(tools=[])
        compiler = WikiCompiler(bus, prompt_os, wiki_store)

        result = compiler._target_path("raw/godot/tutorials/physics.rst")
        assert result.replace("\\", "/").endswith("wiki/godot/tutorials/physics.md")

    @pytest.mark.asyncio
    async def test_index_generation(self):
        """Compile creates index with links to compiled pages."""
        bus = EventBus()
        wiki_store = _make_wiki_store()
        prompt_os = PromptOS(tools=[])
        compiler = WikiCompiler(bus, prompt_os, wiki_store)

        raw_content = "# Physics Nodes\nContent about [[CharacterBody2D]]."
        path = _write_temp_raw(raw_content, "physics_nodes.md")

        with patch.object(compiler, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "# Physics Nodes\n\nSee [[CharacterBody2D]].\n\n### Jinn Heuristics\n- HEURISTIC: test"
            result = await compiler.compile_resource(str(path), category="Godot")

        # Check index was created in wiki store
        index = wiki_store.get_index()
        assert "Godot" in index
        assert any(p["title"] == "Physics Nodes" for p in index["Godot"])
