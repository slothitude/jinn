import json

import pytest

from src.core.bus import EventBus
from src.core.models import AgentState, Event, PlanGraph, PlanNode, ToolCall
from src.agents.buddy import BuddyAgent
from src.agents.kairos import KairosAgent
from src.execution.toolbox import ToolExecutor
from src.promptos.engine import render_graph, PromptOS
from src.core.models import AgentRequest
from src.core.query_engine import QueryEngine


# --- PlanNode model tests ---


def test_plan_node_with_tool_spec():
    node = PlanNode(id=1, action="Create directory", tool="bash", tool_args={"command": "mkdir -p src"})
    assert node.tool == "bash"
    assert node.tool_args == {"command": "mkdir -p src"}


def test_plan_node_without_tool_spec():
    node = PlanNode(id=2, action="Analyze code")
    assert node.tool is None
    assert node.tool_args is None


def test_plan_node_validation_rejects_tool_without_args():
    with pytest.raises(Exception, match="tool.*specified without tool_args"):
        PlanNode(id=3, action="Bad node", tool="bash")


def test_plan_node_validation_rejects_args_without_tool():
    with pytest.raises(Exception, match="tool_args specified without tool"):
        PlanNode(id=4, action="Bad node", tool_args={"command": "echo"})


# --- QueryEngine parsing tests ---


def test_parse_plan_with_tool_specs():
    engine = QueryEngine(EventBus())
    plan_json = json.dumps({
        "nodes": [
            {"id": 1, "action": "Create dir", "tool": "bash", "tool_args": {"command": "mkdir foo"}},
            {"id": 2, "action": "Think"},
        ],
    })
    plan = engine._parse_plan(plan_json)
    assert plan is not None
    assert plan.nodes[0].tool == "bash"
    assert plan.nodes[1].tool is None


def test_parse_plan_strips_unknown_tools():
    engine = QueryEngine(EventBus())
    plan_json = json.dumps({
        "nodes": [
            {"id": 1, "action": "Do thing", "tool": "nonexistent_tool", "tool_args": {"x": 1}},
            {"id": 2, "action": "Safe", "tool": "bash", "tool_args": {"command": "echo hi"}},
        ],
    })
    plan = engine._parse_plan(plan_json)
    assert plan is not None
    # Unknown tool stripped to None
    assert plan.nodes[0].tool is None
    assert plan.nodes[0].tool_args is None
    # Known tool preserved
    assert plan.nodes[1].tool == "bash"


# --- BUDDY fast-path / slow-path tests ---


@pytest.mark.asyncio
async def test_buddy_fast_path_executes_tool_directly():
    bus = EventBus()
    kairos = KairosAgent(bus)
    buddy = BuddyAgent(bus)
    executor = ToolExecutor(bus)
    buddy.set_tool_executor(executor)

    plan = PlanGraph(nodes=[
        PlanNode(id=1, action="Say hello", tool="bash", tool_args={"command": "echo fast_path"}),
    ])
    state = AgentState(session_id="fast-test", execution_graph=plan)

    chunks = []
    async for chunk in buddy.execute("test", state):
        chunks.append(chunk)
    full = "".join(chunks)

    assert "fast_path" in full
    assert plan.nodes[0].status == "completed"


@pytest.mark.asyncio
async def test_buddy_slow_path_for_free_text_node():
    bus = EventBus()
    buddy = BuddyAgent(bus)
    # No tool executor wired — always slow path via stream_llm fallback

    plan = PlanGraph(nodes=[
        PlanNode(id=1, action="Think about something"),
    ])
    state = AgentState(session_id="slow-test", execution_graph=plan)

    chunks = []
    async for chunk in buddy.execute("test", state):
        chunks.append(chunk)

    # Should have yielded content (either LLM or echo fallback)
    assert len(chunks) > 0


# --- Template tests ---


@pytest.mark.asyncio
async def test_ultraplan_template_includes_tools():
    from src.execution.toolbox import DEFAULT_TOOLS

    result = await render_graph(
        ["base/system", "agents/ultraplan"],
        {"memories": [], "tools_list": DEFAULT_TOOLS, "query": "test task", "user_permission_level": 2},
    )
    # Should now include tool schemas
    assert "bash" in result.lower()
    assert "Available Tools" in result
    # Should include tool-aware output format instructions
    assert "tool_args" in result


# --- KAIROS safety gate on fast path ---


@pytest.mark.asyncio
async def test_kairos_safety_gate_on_fast_path():
    bus = EventBus()
    kairos = KairosAgent(bus)
    buddy = BuddyAgent(bus)
    executor = ToolExecutor(bus)
    buddy.set_tool_executor(executor)

    plan = PlanGraph(nodes=[
        PlanNode(id=1, action="Dangerous", tool="bash", tool_args={"command": "rm -rf /"}),
    ])
    state = AgentState(session_id="safety-test", execution_graph=plan)

    chunks = []
    async for chunk in buddy.execute("test", state):
        chunks.append(chunk)
    full = "".join(chunks)

    # Tool should be blocked by KAIROS
    assert "blocked" in full.lower() or "failed" in full.lower() or "FAST PATH FAILED" in full
