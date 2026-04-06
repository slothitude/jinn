import tempfile

import pytest

from src.core.bus import EventBus
from src.core.models import AgentRequest, AgentState, Event
from src.core.query_engine import QueryEngine
from src.agents.buddy import BuddyAgent
from src.agents.kairos import KairosAgent
from src.agents.ultraplan import UltraplanAgent
from src.memory.store import MemoryStore
from src.memory.retrieval import retrieve
from src.feedback.trace_logger import TraceLogger
from src.feedback.observability import register_feedback_hooks


@pytest.fixture
def system():
    bus = EventBus()
    store = MemoryStore(db_path=tempfile.mktemp(suffix=".db"))
    trace_logger = TraceLogger(db_path=tempfile.mktemp(suffix=".db"))
    register_feedback_hooks(bus, trace_logger)

    engine = QueryEngine(bus)
    engine.register_agent(BuddyAgent(bus))
    engine.register_agent(KairosAgent(bus))
    engine.register_agent(UltraplanAgent(bus))
    engine.memory_retriever = lambda q, strategy: retrieve(q, strategy, store)

    return bus, engine, store, trace_logger


@pytest.mark.asyncio
async def test_full_pipeline_buddy(system):
    bus, engine, store, trace_logger = system
    state = AgentState(session_id="int-test-1")
    request = AgentRequest(session_id="int-test-1", input_text="code a function")

    response = await engine.process(request, state)
    assert isinstance(response, str)
    assert len(response) > 0
    assert len(state.history) == 1


@pytest.mark.asyncio
async def test_full_pipeline_ultraplan(system):
    bus, engine, store, trace_logger = system
    state = AgentState(session_id="int-test-2")
    request = AgentRequest(session_id="int-test-2", input_text="plan the migration")

    response = await engine.process(request, state)
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_memory_round_trip(system):
    bus, engine, store, trace_logger = system
    from src.memory.schema import MemoryUnit

    # Store a memory
    store.put(MemoryUnit(
        summary="User prefers Python",
        tags=["preference"],
        importance=0.9,
        prompt_fragment="Default to Python for code generation",
    ))

    # Retrieve for buddy
    results = await retrieve("code help", "buddy", store, k=5)
    assert len(results) == 1
    assert "Python" in results[0].summary


@pytest.mark.asyncio
async def test_event_bus_priority():
    bus = EventBus()
    order = []

    async def first(payload):
        order.append("first")

    async def second(payload):
        order.append("second")

    bus.subscribe(Event.AGENT_CHUNK, second, priority=100)
    bus.subscribe(Event.AGENT_CHUNK, first, priority=0)

    await bus.emit(Event.AGENT_CHUNK, {})
    assert order == ["first", "second"]


@pytest.mark.asyncio
async def test_trace_logging(system):
    _, _, _, trace_logger = system
    from src.feedback.trace_logger import DecisionTrace

    trace = DecisionTrace(
        session_id="trace-test",
        policy_decision={"agent": "BUDDY"},
        outcome="success",
    )
    trace_logger.record(trace)

    traces = trace_logger.get_by_session("trace-test")
    assert len(traces) == 1
    assert traces[0].outcome == "success"


@pytest.mark.asyncio
async def test_kairos_anomaly_detection():
    bus = EventBus()
    kairos = KairosAgent(bus)
    assert not kairos.detect_anomaly({"chunk": "this is fine"})
    assert not kairos.detect_anomaly({"chunk": "all good here"})
    assert kairos.detect_anomaly({"chunk": "timeout exceeded"})
