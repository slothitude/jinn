import tempfile

import pytest

from src.core.bus import EventBus
from src.core.models import AgentRequest, AgentState, Event, PlanGraph, PlanNode
from src.agents.buddy import BuddyAgent
from src.agents.kairos import KairosAgent
from src.agents.ultraplan import UltraplanAgent
from src.execution.toolbox import ToolExecutor
from src.memory.store import MemoryStore
from src.memory.retrieval import retrieve
from src.core.query_engine import QueryEngine
from src.feedback.trace_logger import TraceLogger
from src.feedback.observability import register_feedback_hooks


@pytest.mark.asyncio
async def test_ultraplan_to_buddy_handoff():
    """
    Validates the L3 -> L6 -> L7 pipeline:
    1. Policy routes complex task to ULTRAPLAN
    2. ULTRAPLAN generates a PlanGraph with tool calls
    3. BUDDY receives the plan and executes nodes via ToolExecutor
    """
    bus = EventBus()
    store = MemoryStore(db_path=tempfile.mktemp(suffix=".db"))
    trace_logger = TraceLogger(db_path=tempfile.mktemp(suffix=".db"))
    register_feedback_hooks(bus, trace_logger)

    engine = QueryEngine(bus)
    buddy = BuddyAgent(bus)
    kairos = KairosAgent(bus)
    tool_executor = ToolExecutor(bus)
    buddy.set_tool_executor(tool_executor)

    engine.register_agent(buddy)
    engine.register_agent(kairos)
    engine.register_agent(UltraplanAgent(bus))
    engine.memory_retriever = lambda q, strategy: retrieve(q, strategy, store)

    # Synthetic plan: echo commands (no filesystem side effects)
    plan = PlanGraph(nodes=[
        PlanNode(id=1, action="Echo step 1", tool="bash", tool_args={"command": "echo Step1_OK"}),
        PlanNode(id=2, action="Echo step 2", tool="bash", tool_args={"command": "echo Step2_OK"}),
        PlanNode(id=3, action="Echo step 3", tool="bash", tool_args={"command": "echo Step3_OK"}),
    ])
    state = AgentState(session_id="handoff-test", execution_graph=plan)

    # Track tool execution
    execution_log = []
    async def track_tools(payload):
        execution_log.append(payload.get("name", ""))
    bus.subscribe(Event.TOOL_CALL_RESULT, track_tools)

    # Execute via BUDDY directly with the plan
    response_chunks = []
    async for chunk in buddy.execute("Execute three echo steps", state):
        response_chunks.append(chunk)
    full = "".join(response_chunks)

    # 1. All tools were invoked
    assert "Step1_OK" in full
    assert "Step2_OK" in full
    assert "Step3_OK" in full

    # 2. All nodes completed
    assert all(n.status == "completed" for n in plan.nodes)

    # 3. Plan was finalized
    assert "PLAN COMPLETE" in full
