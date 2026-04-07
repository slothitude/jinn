import time

import pytest

from src.core.bus import EventBus
from src.core.models import Event
from src.core.registry import wire
from src.memory.autodream import AutoDream
from src.memory.schema import MemoryUnit
from src.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(db_path=tmp_path / "test_autodream.db")
    yield s
    s.close()


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def dreamer(bus, store):
    d = AutoDream(bus, store)
    wire(bus, d)
    return d


# --- Test 1: TOOL_CALL_RESULT payload includes output ---


@pytest.mark.asyncio
async def test_tool_call_result_includes_output(bus, dreamer):
    """TOOL_CALL_RESULT payload now has output field."""
    captured = {}
    bus.subscribe(Event.TOOL_CALL_RESULT, lambda p: captured.update(p), priority=0)
    await bus.emit(Event.TOOL_CALL_RESULT, {
        "tool_call_id": "tc1", "name": "bash",
        "success": False, "output": "no such file or directory",
    })
    assert "output" in captured
    assert captured["output"] == "no such file or directory"


# --- Test 2: AutoDream collects failures ---


@pytest.mark.asyncio
async def test_autodream_collects_failure(bus, dreamer):
    """Emitted failed TOOL_CALL_RESULT → _pending_failures has 1 entry."""
    await bus.emit(Event.TOOL_CALL_RESULT, {
        "tool_call_id": "tc1", "name": "bash",
        "success": False, "output": "no such file or directory: /foo/bar",
    })
    assert len(dreamer._pending_failures) == 1
    assert dreamer._pending_failures[0]["name"] == "bash"


# --- Test 3: AutoDream ignores successes ---


@pytest.mark.asyncio
async def test_autodream_ignores_success(bus, dreamer):
    """Successful TOOL_CALL_RESULT → _pending_failures stays empty."""
    await bus.emit(Event.TOOL_CALL_RESULT, {
        "tool_call_id": "tc1", "name": "bash",
        "success": True, "output": "hello",
    })
    assert len(dreamer._pending_failures) == 0


# --- Test 4: Extract heuristics — mkdir pattern ---


def test_extract_heuristics_mkdir_pattern(dreamer):
    failures = [{"name": "bash", "output": "mkdir: no such file or directory: /a/b/c"}]
    units = dreamer._extract_heuristics(failures)
    assert len(units) == 1
    assert "mkdir -p" in units[0].prompt_fragment
    assert "heuristic" in units[0].tags


# --- Test 5: Extract heuristics — no match ---


def test_extract_heuristics_no_match(dreamer):
    failures = [{"name": "bash", "output": "something completely unexpected"}]
    units = dreamer._extract_heuristics(failures)
    assert len(units) == 0


# --- Test 6: Dedup bumps existing heuristic ---


@pytest.mark.asyncio
async def test_dedup_bumps_existing(store, dreamer):
    """Same failure twice → 1 MemoryUnit with bumped importance."""
    original = MemoryUnit(
        summary="mkdir fails without parent directories",
        tags=["heuristic", "failure"],
        importance=0.7,
        prompt_fragment="Always use `mkdir -p`...",
    )
    store.put(original)

    heuristics = [MemoryUnit(
        summary="mkdir fails without parent directories",
        tags=["heuristic", "failure"],
        importance=0.7,
        prompt_fragment="Always use `mkdir -p` to create parent directories automatically.",
    )]
    stored = await dreamer._dedup_and_store(heuristics)
    assert stored == 0  # No new entry — bumped existing

    existing = store.search_by_tag("heuristic")
    assert len(existing) == 1
    assert existing[0].importance > 0.7
    assert existing[0].access_count == 1


# --- Test 7: Dream emits MEMORY_UPDATE ---


@pytest.mark.asyncio
async def test_dream_emits_memory_update(bus, dreamer):
    """Failures present → MEMORY_UPDATE event fires after agent_end."""
    update_payload = {}
    bus.subscribe(Event.MEMORY_UPDATE, lambda p: update_payload.update(p), priority=0)

    # Feed a failure
    await bus.emit(Event.TOOL_CALL_RESULT, {
        "tool_call_id": "tc1", "name": "bash",
        "success": False, "output": "bash: command not found: badcmd",
    })
    # Trigger dreaming
    await bus.emit(Event.AGENT_END, {"agent": "buddy"})

    assert "heuristics_stored" in update_payload
    assert update_payload["heuristics_stored"] == 1


# --- Test 8: Heuristic flows to buddy prompt via retrieval ---


@pytest.mark.asyncio
async def test_heuristic_flows_to_buddy_prompt(bus, store):
    """E2E: store a heuristic, retrieve for buddy role, verify it renders."""
    from src.memory.retrieval import retrieve

    heuristic = MemoryUnit(
        summary="Always verify paths before reading",
        tags=["heuristic", "failure"],
        importance=0.7,
        prompt_fragment="Verify the file path exists with `ls` before reading.",
    )
    store.put(heuristic)

    results = await retrieve("read a file", "buddy", store)
    assert len(results) >= 1
    found = any(h.prompt_fragment and "ls" in h.prompt_fragment for h in results)
    assert found, "Heuristic prompt_fragment should appear in buddy retrieval results"
