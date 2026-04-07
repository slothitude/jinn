"""The Ultimate JINN Test — full cognitive loop, every layer, no LLM required.

8 tests exercise the complete pipeline from user input through policy routing,
memory retrieval, PromptOS assembly, agent execution (mock fallback), EventBus
propagation, tool execution, safety gates, AutoDream consolidation, and
TraceLogger recording.

Run standalone:  python tests/test_ultimate.py
Run via pytest:  pytest tests/test_ultimate.py -v
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import traceback
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.bus import EventBus
from src.core.models import AgentRequest, AgentState, Event, ToolCall
from src.core.query_engine import QueryEngine
from src.core.registry import wire
from src.agents.buddy import BuddyAgent
from src.agents.kairos import KairosAgent
from src.agents.ultraplan import UltraplanAgent
from src.execution.toolbox import ToolExecutor
from src.memory.store import MemoryStore
from src.memory.schema import MemoryUnit
from src.memory.wiki import WikiStore, WikiPage
from src.memory.retrieval import retrieve, retrieve_with_wiki
from src.memory.autodream import AutoDream
from src.feedback.trace_logger import TraceLogger
from src.feedback.observability import register_feedback_hooks

# Patch LLM streaming to fail immediately so agents use their mock fallbacks.
import src.agents.base as _base_mod


async def _fail_stream(*_a, **_kw):
    """Async generator that raises immediately — forces mock fallback."""
    raise RuntimeError("No LLM available in test")
    yield  # noqa: unreachable — makes this an async generator


_base_mod.stream_chat = _fail_stream
_base_mod.stream_chat_with_tools = _fail_stream


# ---------------------------------------------------------------------------
# EventCapture — observer-level subscriber for every Event enum value
# ---------------------------------------------------------------------------

class EventCapture:
    """Subscribes to all Event values at priority 200, accumulates payloads."""

    def __init__(self) -> None:
        self.events: dict[str, list[dict]] = {}

    def subscribe_to_all(self, bus: EventBus) -> None:
        for event in Event:
            key = event.value
            self.events.setdefault(key, [])

            async def _cb(payload, _key=key):
                self.events[_key].append(payload or {})

            bus.subscribe(event.value, _cb, priority=200)

    def get(self, event: Event) -> list[dict]:
        return self.events.get(event.value, [])


# ---------------------------------------------------------------------------
# _build_full_system — mirrors main.py wiring with temp databases
# ---------------------------------------------------------------------------

def _build_full_system():
    """Wire every layer with temp SQLite databases. Returns all components."""
    bus = EventBus(max_history=100)

    store = MemoryStore(db_path=tempfile.mktemp(suffix=".db"))
    wiki_store = WikiStore(db_path=tempfile.mktemp(suffix=".db"))
    autodream = AutoDream(bus, store)

    buddy = BuddyAgent(bus)
    kairos = KairosAgent(bus)
    ultraplan = UltraplanAgent(bus)

    wire(bus, autodream, kairos, buddy)

    tool_executor = ToolExecutor(bus)
    buddy.set_tool_executor(tool_executor)

    trace_logger = TraceLogger(db_path=tempfile.mktemp(suffix=".db"))
    register_feedback_hooks(bus, trace_logger)

    engine = QueryEngine(bus)
    engine.register_agent(buddy)
    engine.register_agent(kairos)
    engine.register_agent(ultraplan)
    engine.memory_retriever = lambda q, strategy: retrieve(q, strategy, store)
    engine.wiki_retriever = lambda q, strategy: retrieve_with_wiki(
        q, strategy, store, wiki_store
    )

    capture = EventCapture()
    capture.subscribe_to_all(bus)

    state = AgentState(session_id="ultimate-test")

    return (
        bus, engine, store, wiki_store, autodream,
        buddy, kairos, ultraplan, tool_executor,
        trace_logger, capture, state,
    )


def _cleanup(components):
    """Close all database connections."""
    _, _, store, wiki_store, _, _, _, _, _, trace_logger, _, _ = components
    store.close()
    wiki_store.close()
    trace_logger.close()


# ---------------------------------------------------------------------------
# Test 1: Seed data and verify retrieval
# ---------------------------------------------------------------------------

async def test_seed_data_and_verify_retrieval():
    sys_components = _build_full_system()

    try:
        _, _, store, wiki_store, _, _, _, _, _, _, _, _ = sys_components

        # Seed 3 MemoryUnits
        store.put(MemoryUnit(
            summary="User prefers dark mode",
            tags=["preference"],
            importance=0.9,
            prompt_fragment="Default to dark theme",
        ))
        store.put(MemoryUnit(
            summary="Deploy failed due to missing env var",
            tags=["failure"],
            importance=0.7,
            prompt_fragment="Always check .env before deploying",
        ))
        store.put(MemoryUnit(
            summary="Use async for all I/O operations",
            tags=["heuristic"],
            importance=0.8,
            prompt_fragment="Prefer async/await over sync calls",
        ))
        assert store.count() == 3

        # search_by_tag returns correct summaries and prompt_fragments
        prefs = store.search_by_tag("preference")
        assert len(prefs) == 1
        assert "dark mode" in prefs[0].summary
        assert prefs[0].prompt_fragment == "Default to dark theme"

        heuristics = store.search_by_tag("heuristic")
        assert len(heuristics) == 1
        assert "async" in heuristics[0].summary
        assert heuristics[0].prompt_fragment == "Prefer async/await over sync calls"

        # Seed 2 WikiPages
        wiki_store.put(WikiPage(
            title="EventBus Overview",
            category="Architecture",
            summary="Core pub/sub backbone with priority-based execution",
            content="The EventBus is the reactive backbone of JINN...",
        ))
        wiki_store.put(WikiPage(
            title="Python Style Guide",
            category="Reference",
            summary="Code style conventions for the project",
            content="Follow PEP 8 with some exceptions...",
        ))

        index = wiki_store.get_index()
        assert "Architecture" in index
        assert "Reference" in index

        # retrieve() for buddy role returns preference + heuristic
        results = await retrieve("code help", "buddy", store, k=10)
        tags_seen = set()
        for m in results:
            tags_seen.update(m.tags)
        assert "preference" in tags_seen
        assert "heuristic" in tags_seen

        # retrieve_with_wiki() returns dict with memories and wiki_pages keys
        result = await retrieve_with_wiki("EventBus", "buddy", store, wiki_store)
        assert "memories" in result
        assert "wiki_pages" in result
        assert "wiki_index" in result

    finally:
        _cleanup(sys_components)


# ---------------------------------------------------------------------------
# Test 2: Simple query through full pipeline
# ---------------------------------------------------------------------------

async def test_simple_query_full_pipeline():
    sys_components = _build_full_system()

    try:
        _, engine, _, _, _, _, _, _, _, trace_logger, capture, state = sys_components

        request = AgentRequest(session_id=state.session_id, input_text="code a function")
        response = await engine.process(request, state)

        # Non-empty string response
        assert isinstance(response, str)
        assert len(response) > 0

        # State updated correctly
        assert state.turn_count == 1
        assert len(state.history) == 1
        assert state.history[0]["user"] == "code a function"

        # Event sequence: TURN_START -> AGENT_START(BUDDY) -> AGENT_CHUNK* -> AGENT_END(BUDDY) -> TURN_END
        turn_starts = capture.get(Event.TURN_START)
        agent_starts = capture.get(Event.AGENT_START)
        agent_chunks = capture.get(Event.AGENT_CHUNK)
        agent_ends = capture.get(Event.AGENT_END)
        turn_ends = capture.get(Event.TURN_END)

        assert len(turn_starts) == 1
        assert len(agent_starts) >= 1
        assert agent_starts[0]["agent"] == "BUDDY"
        assert len(agent_chunks) > 0
        buddy_chunks = [c for c in agent_chunks if c["agent"] == "BUDDY"]
        assert len(buddy_chunks) > 0
        assert len(agent_ends) >= 1
        buddy_ends = [e for e in agent_ends if e["agent"] == "BUDDY"]
        assert len(buddy_ends) >= 1
        assert len(turn_ends) == 1
        assert turn_ends[0]["agent"] == "BUDDY"
        assert turn_ends[0]["status"] == "complete"

        # TraceLogger recorded 1 trace for the session
        traces = trace_logger.get_by_session(state.session_id)
        assert len(traces) == 1

    finally:
        _cleanup(sys_components)


# ---------------------------------------------------------------------------
# Test 3: Complex query routes to ULTRAPLAN
# ---------------------------------------------------------------------------

async def test_complex_query_routes_to_ultraplan():
    sys_components = _build_full_system()

    try:
        _, engine, _, _, _, _, _, _, _, _, capture, state = sys_components

        # Long query with architecture keywords to trigger ULTRAPLAN
        long_query = (
            "plan the architecture migration from monolith to microservice "
            "with distributed caching, pipeline orchestration, and database design "
            "for a full-stack scalable infrastructure deployment. "
            "We need to overhaul the security audit process and redesign the system."
        )
        request = AgentRequest(session_id=state.session_id, input_text=long_query)

        # Verify PolicyEngine routes to ULTRAPLAN
        decision = await engine.policy.decide(request)
        assert decision.agent_id == "ULTRAPLAN"
        assert decision.memory_strategy == "deep"

        response = await engine.process(request, state)
        assert isinstance(response, str)
        assert len(response) > 0

        # Capture contains ULTRAPLAN agent events
        agent_starts = capture.get(Event.AGENT_START)
        agent_chunks = capture.get(Event.AGENT_CHUNK)
        agent_ends = capture.get(Event.AGENT_END)
        turn_ends = capture.get(Event.TURN_END)

        ultraplan_starts = [e for e in agent_starts if e["agent"] == "ULTRAPLAN"]
        assert len(ultraplan_starts) >= 1

        ultraplan_chunks = [e for e in agent_chunks if e["agent"] == "ULTRAPLAN"]
        assert len(ultraplan_chunks) > 0

        ultraplan_ends = [e for e in agent_ends if e["agent"] == "ULTRAPLAN"]
        assert len(ultraplan_ends) >= 1

        assert turn_ends[-1]["agent"] == "ULTRAPLAN"

    finally:
        _cleanup(sys_components)


# ---------------------------------------------------------------------------
# Test 4: AutoDream consolidation from tool failure
# ---------------------------------------------------------------------------

async def test_autodream_consolidation_from_tool_failure():
    sys_components = _build_full_system()

    try:
        bus, _, store, _, _, _, _, _, _, _, capture, _ = sys_components

        # Emit a TOOL_CALL_RESULT with failure, then AGENT_END to trigger AutoDream
        await bus.emit(Event.TOOL_CALL_RESULT, {
            "tool_call_id": "tc-1",
            "name": "bash",
            "success": False,
            "output": "command not found: badcmd",
        })
        await bus.emit(Event.AGENT_END, {"agent": "BUDDY"})

        # AutoDream should have extracted a heuristic
        heuristics = store.search_by_tag("heuristic")
        assert len(heuristics) >= 1

        found = False
        for h in heuristics:
            if "Command not found" in h.summary:
                assert "Verify installation" in h.prompt_fragment
                found = True
        assert found, f"Expected 'Command not found' heuristic, got {[h.summary for h in heuristics]}"

        # Capture has MEMORY_UPDATE from autodream
        mem_updates = capture.get(Event.MEMORY_UPDATE)
        assert len(mem_updates) >= 1
        autodream_updates = [u for u in mem_updates if u.get("source") == "autodream"]
        assert len(autodream_updates) >= 1
        assert autodream_updates[0]["heuristics_stored"] >= 1

    finally:
        _cleanup(sys_components)


# ---------------------------------------------------------------------------
# Test 5: Tool execution events
# ---------------------------------------------------------------------------

async def test_tool_execution_events():
    sys_components = _build_full_system()

    # Create a temp file for the read tool
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
    tmp.write("ultimate test content here")
    tmp.close()

    try:
        _, _, _, _, _, _, _, _, tool_executor, _, capture, _ = sys_components

        # Execute bash (safe command)
        bash_result = await tool_executor.execute(ToolCall(
            id="tc-bash-1",
            name="bash",
            arguments='{"command": "echo ultimate_test"}',
        ))
        assert bash_result.success is True
        assert "ultimate_test" in bash_result.output

        # Execute read
        read_result = await tool_executor.execute(ToolCall(
            id="tc-read-1",
            name="read",
            arguments=json.dumps({"path": tmp.name.replace("\\", "/")}),
        ))
        assert read_result.success is True
        assert "ultimate test content" in read_result.output

        # Verify events: TOOL_CALL_REQUEST before TOOL_CALL_RESULT for each call
        requests = capture.get(Event.TOOL_CALL_REQUEST)
        results = capture.get(Event.TOOL_CALL_RESULT)

        assert len(requests) >= 2
        assert len(results) >= 2

        # Each request has correct name
        bash_req = [r for r in requests if r.get("name") == "bash"]
        read_req = [r for r in requests if r.get("name") == "read"]
        assert len(bash_req) >= 1
        assert len(read_req) >= 1

        # Results have correct success fields
        bash_res = [r for r in results if r.get("name") == "bash"]
        read_res = [r for r in results if r.get("name") == "read"]
        assert all(r["success"] for r in bash_res)
        assert all(r["success"] for r in read_res)

    finally:
        Path(tmp.name).unlink(missing_ok=True)
        _cleanup(sys_components)


# ---------------------------------------------------------------------------
# Test 6: KAIROS safety blocks dangerous command
# ---------------------------------------------------------------------------

async def test_kairos_safety_blocks_dangerous_command():
    sys_components = _build_full_system()

    try:
        bus, _, _, _, _, _, _, _, tool_executor, _, _, _ = sys_components

        result = await tool_executor.execute(ToolCall(
            id="tc-danger-1",
            name="bash",
            arguments='{"command": "rm -rf /"}',
        ))

        assert result.success is False
        assert "blocked" in result.output.lower()

        # Bus history records TOOL_CALL_REQUEST was emitted (history is saved
        # before subscribers run, so it captures cancelled events too)
        history = bus.get_history()
        request_events = [h for h in history if h[0] == Event.TOOL_CALL_REQUEST.value]
        assert len(request_events) >= 1
        danger_payloads = [h[1] for h in request_events if h[1].get("name") == "bash"]
        assert len(danger_payloads) >= 1

        # No TOOL_CALL_RESULT for this call (cancelled before dispatch)
        result_events = [h for h in history if h[0] == Event.TOOL_CALL_RESULT.value]
        danger_results = [
            h[1] for h in result_events
            if h[1].get("tool_call_id") == "tc-danger-1"
        ]
        assert len(danger_results) == 0

    finally:
        _cleanup(sys_components)


# ---------------------------------------------------------------------------
# Test 7: Wiki retrieval injects into context
# ---------------------------------------------------------------------------

async def test_wiki_retrieval_injects_into_context():
    sys_components = _build_full_system()

    try:
        _, engine, _, wiki_store, _, _, _, _, _, _, _, state = sys_components

        # Seed wiki pages
        wiki_store.put(WikiPage(
            title="Agent Lifecycle",
            category="Architecture",
            summary="How agents are created, executed, and terminated",
            content="Agents follow a lifecycle of init -> execute -> end...",
        ))
        wiki_store.put(WikiPage(
            title="EventBus API Reference",
            category="Reference",
            summary="Complete API reference for the EventBus",
            content="The EventBus provides subscribe, emit, once, wait_for...",
        ))

        # Call wiki_retriever — use simple query that matches the wiki page titles/summaries
        wiki_data = await engine.wiki_retriever("EventBus", "standard")
        assert "wiki_pages" in wiki_data
        assert len(wiki_data["wiki_pages"]) >= 1

        # wiki_index has both categories
        assert "Architecture" in wiki_data["wiki_index"]
        assert "Reference" in wiki_data["wiki_index"]

        # Assemble prompt via PromptOS
        request = AgentRequest(
            session_id=state.session_id,
            input_text="How does the EventBus work?",
        )
        prompt = await engine.prompt_os.assemble(request, wiki_data, "BUDDY")

        # Assembled prompt contains "COMPILED KNOWLEDGE" and a page title
        assert "COMPILED KNOWLEDGE" in prompt
        assert "EventBus API Reference" in prompt

    finally:
        _cleanup(sys_components)


# ---------------------------------------------------------------------------
# Test 8: Multi-turn conversation state accumulation
# ---------------------------------------------------------------------------

async def test_multi_turn_conversation_state_accumulation():
    sys_components = _build_full_system()

    try:
        _, engine, _, _, _, _, _, _, _, trace_logger, capture, state = sys_components

        # Turn 1: BUDDY
        r1 = AgentRequest(session_id=state.session_id, input_text="code a hello world function")
        await engine.process(r1, state)

        # Turn 2: BUDDY
        r2 = AgentRequest(session_id=state.session_id, input_text="explain how recursion works")
        await engine.process(r2, state)

        # Turn 3: ULTRAPLAN (complex query)
        r3 = AgentRequest(
            session_id=state.session_id,
            input_text=(
                "plan the architecture migration from monolith to microservice "
                "with distributed caching, pipeline infrastructure, and database design"
            ),
        )
        await engine.process(r3, state)

        # State accumulation
        assert state.turn_count == 3
        assert len(state.history) == 3
        assert "hello world" in state.history[0]["user"]
        assert "recursion" in state.history[1]["user"]
        assert "architecture migration" in state.history[2]["user"]

        # TraceLogger has 3 traces for the session
        traces = trace_logger.get_by_session(state.session_id)
        assert len(traces) == 3

        # Event counts
        assert len(capture.get(Event.TURN_START)) == 3
        assert len(capture.get(Event.TURN_END)) == 3

        # Agent distribution: at least 2 BUDDY starts and at least 1 ULTRAPLAN start
        agent_starts = capture.get(Event.AGENT_START)
        buddy_starts = [e for e in agent_starts if e["agent"] == "BUDDY"]
        ultraplan_starts = [e for e in agent_starts if e["agent"] == "ULTRAPLAN"]
        assert len(buddy_starts) >= 2
        assert len(ultraplan_starts) >= 1

    finally:
        _cleanup(sys_components)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    test_seed_data_and_verify_retrieval,
    test_simple_query_full_pipeline,
    test_complex_query_routes_to_ultraplan,
    test_autodream_consolidation_from_tool_failure,
    test_tool_execution_events,
    test_kairos_safety_blocks_dangerous_command,
    test_wiki_retrieval_injects_into_context,
    test_multi_turn_conversation_state_accumulation,
]


def main():
    import json as _json  # noqa: E402 (needed by test 5 inline)

    passed = 0
    failed = 0
    errors = []

    for test in ALL_TESTS:
        name = test.__name__
        try:
            asyncio.run(test())
            print(f"  PASS  {name}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {name}")
            traceback.print_exc()
            errors.append((name, exc))
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if errors:
        for name, exc in errors:
            print(f"  FAILED: {name}: {exc}")
    print(f"{'=' * 50}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------------------
# Pytest wrappers (work when pytest environment is functional)
# ---------------------------------------------------------------------------

try:
    import pytest

    for _t in ALL_TESTS:
        _wrapper = pytest.mark.asyncio(_t)
        _wrapper.__module__ = __name__
        globals()[_t.__name__] = _wrapper
except ImportError:
    pass
