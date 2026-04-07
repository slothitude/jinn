"""Tests for Cognitive Assembly Engine features:
1. Coding macros (language-specific SOPs)
2. Safety-level tool filtering
3. Priority-sorted heuristics
4. Wiki/knowledge index
"""

import pytest

from jinja2.nativetypes import NativeEnvironment
from pathlib import Path

from src.promptos.engine import PromptOS, render_graph, _env
from src.core.models import AgentRequest
from src.execution.toolbox import ToolSchema
from src.memory.wiki import WikiPage, WikiStore


_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


# ============================================================
# 1. Coding Macros
# ============================================================


@pytest.mark.asyncio
async def test_coding_macro_python():
    """enforce_style('python') renders PEP8 rules."""
    tpl = _env.from_string(
        '{% import "macros/coding.jinja" as coding %}{{ coding.enforce_style("python") }}'
    )
    result = await tpl.render_async()
    assert "PEP8" in result
    assert "pathlib" in result


@pytest.mark.asyncio
async def test_coding_macro_typescript():
    """enforce_style('typescript') renders strict TS rules."""
    tpl = _env.from_string(
        '{% import "macros/coding.jinja" as coding %}{{ coding.enforce_style("typescript") }}'
    )
    result = await tpl.render_async()
    assert "strict" in result.lower()
    assert "interface" in result


@pytest.mark.asyncio
async def test_coding_macro_unknown_language():
    """Unknown language renders generic guidelines."""
    tpl = _env.from_string(
        '{% import "macros/coding.jinja" as coding %}{{ coding.enforce_style("brainfuck") }}'
    )
    result = await tpl.render_async()
    assert "Keep functions small" in result


@pytest.mark.asyncio
async def test_coding_macro_testing():
    """enforce_testing macro renders language-specific testing rules."""
    tpl = _env.from_string(
        '{% import "macros/coding.jinja" as coding %}{{ coding.enforce_testing("python") }}'
    )
    result = await tpl.render_async()
    assert "pytest" in result.lower() or "test_" in result


# ============================================================
# 2. Safety-Level Tool Filtering
# ============================================================


@pytest.mark.asyncio
async def test_tool_schema_has_safety_level():
    """ToolSchema includes safety_level field."""
    from src.execution.toolbox import BASH_TOOL, READ_TOOL, WRITE_TOOL

    assert BASH_TOOL.safety_level == 2
    assert READ_TOOL.safety_level == 0
    assert WRITE_TOOL.safety_level == 1


@pytest.mark.asyncio
async def test_full_permission_sees_all_tools():
    """Permission level 2 sees all tools including dangerous ones."""
    tools = [
        ToolSchema(name="safe_tool", description="Safe", parameters={"type": "object", "properties": {}}, safety_level=0),
        ToolSchema(name="dangerous_tool", description="Dangerous", parameters={"type": "object", "properties": {}}, safety_level=2),
    ]
    result = await render_graph(["base/system", "agents/buddy"], {
        "memories": [],
        "tools_list": tools,
        "user_permission_level": 2,
    })
    assert "safe_tool" in result
    assert "dangerous_tool" in result


@pytest.mark.asyncio
async def test_low_permission_hides_dangerous_tools():
    """Permission level 0 hides safety_level > 0 tools."""
    tools = [
        ToolSchema(name="safe_tool", description="Safe", parameters={"type": "object", "properties": {}}, safety_level=0),
        ToolSchema(name="moderate_tool", description="Moderate", parameters={"type": "object", "properties": {}}, safety_level=1),
        ToolSchema(name="dangerous_tool", description="Dangerous", parameters={"type": "object", "properties": {}}, safety_level=2),
    ]
    result = await render_graph(["base/system", "agents/buddy"], {
        "memories": [],
        "tools_list": tools,
        "user_permission_level": 0,
    })
    assert "safe_tool" in result
    assert "moderate_tool" not in result
    assert "dangerous_tool" not in result


@pytest.mark.asyncio
async def test_medium_permission_sees_safe_and_moderate():
    """Permission level 1 sees safe + moderate but not dangerous."""
    tools = [
        ToolSchema(name="safe_tool", description="Safe", parameters={"type": "object", "properties": {}}, safety_level=0),
        ToolSchema(name="moderate_tool", description="Moderate", parameters={"type": "object", "properties": {}}, safety_level=1),
        ToolSchema(name="dangerous_tool", description="Dangerous", parameters={"type": "object", "properties": {}}, safety_level=2),
    ]
    result = await render_graph(["base/system", "agents/buddy"], {
        "memories": [],
        "tools_list": tools,
        "user_permission_level": 1,
    })
    assert "safe_tool" in result
    assert "moderate_tool" in result
    assert "dangerous_tool" not in result


# ============================================================
# 3. Priority-Sorted Heuristics
# ============================================================


@pytest.mark.asyncio
async def test_heuristics_render_with_priority():
    """Heuristics display PRIORITY prefix with importance value."""
    memories = [
        type("M", (), {"tags": ["heuristic"], "summary": "Use mkdir -p", "importance": 0.7, "prompt_fragment": "Always use mkdir -p"})(),
    ]
    result = await render_graph(
        ["base/system", "agents/buddy"],
        {"memories": memories, "tools_list": []},
    )
    assert "PRIORITY:" in result
    assert "0.7" in result
    assert "Always use mkdir -p" in result


@pytest.mark.asyncio
async def test_heuristics_no_fragment_not_rendered():
    """Memories without prompt_fragment are skipped."""
    memories = [
        type("M", (), {"tags": ["heuristic"], "summary": "No fragment", "importance": 0.9, "prompt_fragment": None})(),
    ]
    result = await render_graph(
        ["base/system", "agents/buddy"],
        {"memories": memories, "tools_list": []},
    )
    assert "PRIORITY:" not in result


# ============================================================
# 4. Wiki/Knowledge Index
# ============================================================


@pytest.mark.asyncio
async def test_wiki_store_crud(tmp_path):
    """WikiStore put/get_index/get_by_category/search round-trip."""
    store = WikiStore(db_path=tmp_path / "test_wiki.db")
    store.put(WikiPage(title="Auth Flow", category="Architecture", summary="OAuth2 PKCE flow"))
    store.put(WikiPage(title="Error Codes", category="Reference", summary="HTTP error code mapping"))
    store.put(WikiPage(title="Data Layer", category="Architecture", summary="SQLite + memory store"))

    index = store.get_index()
    assert "Architecture" in index
    assert len(index["Architecture"]) == 2
    assert "Reference" in index

    arch = store.get_by_category("Architecture")
    assert len(arch) == 2

    results = store.search("OAuth")
    assert len(results) == 1
    assert results[0].title == "Auth Flow"

    store.close()


@pytest.mark.asyncio
async def test_wiki_index_renders_in_template(tmp_path):
    """Wiki pages appear in system prompt when WikiStore is wired."""
    store = WikiStore(db_path=tmp_path / "test_wiki.db")
    store.put(WikiPage(title="Auth Flow", category="Architecture", summary="OAuth2 PKCE flow"))
    store.put(WikiPage(title="Error Codes", category="Reference", summary="HTTP error code mapping"))

    promptos = PromptOS(wiki_store=store)
    result = await promptos.assemble(
        AgentRequest(session_id="t", input_text="explain auth"),
        {"memories": []},
        "BUDDY",
    )
    assert "COMPILED KNOWLEDGE" in result
    assert "Auth Flow" in result
    assert "Error Codes" in result
    assert "Architecture" in result

    store.close()


@pytest.mark.asyncio
async def test_wiki_empty_store_no_section(tmp_path):
    """Empty WikiStore doesn't render COMPILED KNOWLEDGE section."""
    store = WikiStore(db_path=tmp_path / "test_wiki_empty.db")
    promptos = PromptOS(wiki_store=store)
    result = await promptos.assemble(
        AgentRequest(session_id="t", input_text="hello"),
        {"memories": []},
        "BUDDY",
    )
    assert "COMPILED KNOWLEDGE" not in result
    store.close()


@pytest.mark.asyncio
async def test_wiki_no_store_no_error():
    """PromptOS without wiki_store still works — wiki_index defaults to {}."""
    promptos = PromptOS()
    result = await promptos.assemble(
        AgentRequest(session_id="t", input_text="hello"),
        {"memories": []},
        "BUDDY",
    )
    assert "COMPILED KNOWLEDGE" not in result
    assert "BUDDY" in result
