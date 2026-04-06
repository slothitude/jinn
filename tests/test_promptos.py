import pytest
from src.promptos.engine import render_graph, PromptOS
from src.core.models import AgentRequest


@pytest.mark.asyncio
async def test_render_graph_basic():
    result = await render_graph(["base/system"], {})
    assert "COGNITIVE CONTEXT" in result


@pytest.mark.asyncio
async def test_render_graph_buddy():
    result = await render_graph(
        ["base/system", "agents/buddy"],
        {"memories": [], "tools_list": []},
    )
    assert "BUDDY" in result
    assert "collaborative engineering assistant" in result


@pytest.mark.asyncio
async def test_render_graph_ultraplan_with_memory():
    memories = [
        type("M", (), {"tags": ["constraint"], "summary": "Never delete user data", "importance": 0.9, "prompt_fragment": "CRITICAL: Preserve all user data"})(),
        type("M", (), {"tags": ["failure"], "summary": "Broke prod with force push", "importance": 0.8, "prompt_fragment": "Always use --no-force"})(),
    ]
    result = await render_graph(
        ["base/system", "agents/ultraplan"],
        {"memories": memories, "tools_list": []},
    )
    assert "Active Constraints" in result
    assert "Never delete user data" in result
    assert "Past Failures" in result


@pytest.mark.asyncio
async def test_render_graph_kairos():
    result = await render_graph(
        ["base/system", "agents/kairos"],
        {"memories": [], "tools_list": []},
    )
    assert "KAIROS" in result
    assert "interrupt-driven" in result


@pytest.mark.asyncio
async def test_promptos_assemble():
    promptos = PromptOS()
    request = AgentRequest(session_id="test", input_text="hello")
    result = await promptos.assemble(request, {"memories": []}, "BUDDY")
    assert "BUDDY" in result


@pytest.mark.asyncio
async def test_memory_macros_filter_by_tag():
    memories = [
        type("M", (), {"tags": ["preference"], "summary": "Dark mode", "importance": 0.7, "prompt_fragment": "Use dark theme"})(),
        type("M", (), {"tags": ["constraint"], "summary": "No force push", "importance": 0.9, "prompt_fragment": None})(),
        type("M", (), {"tags": ["failure"], "summary": "Broke CI", "importance": 0.8, "prompt_fragment": "Check CI first"})(),
    ]
    result = await render_graph(
        ["base/system", "agents/buddy"],
        {"memories": memories, "tools_list": []},
    )
    # BUDDY should see preferences, NOT failures
    assert "Dark mode" in result
    assert "Broke CI" not in result


@pytest.mark.asyncio
async def test_plan_execute_flow():
    result = await render_graph(["flows/plan_execute"], {})
    assert "Decompose into subtasks" in result
