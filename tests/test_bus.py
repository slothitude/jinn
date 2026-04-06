import asyncio

import pytest

from src.core.bus import EventBus
from src.core.models import Event, EventCancelled, EventResult


# --- Error isolation ---

@pytest.mark.asyncio
async def test_error_isolation_one_bad_subscriber_does_not_break_others():
    bus = EventBus()
    results = []

    async def good(payload):
        results.append("good")

    async def bad(payload):
        raise RuntimeError("boom")

    async def also_good(payload):
        results.append("also_good")

    bus.subscribe("test", good, priority=0)
    bus.subscribe("test", bad, priority=50)
    bus.subscribe("test", also_good, priority=100)

    result = await bus.emit("test", {})
    assert results == ["good", "also_good"]
    assert result.delivered == 2
    assert len(result.errors) == 1
    assert isinstance(result.errors[0], RuntimeError)


# --- Cancellation ---

@pytest.mark.asyncio
async def test_event_cancelled_stops_propagation():
    bus = EventBus()
    results = []

    async def blocker(payload):
        results.append("blocker")
        raise EventCancelled("blocked!")

    async def never_called(payload):
        results.append("should_not_run")

    bus.subscribe("test", blocker, priority=0)
    bus.subscribe("test", never_called, priority=100)

    result = await bus.emit("test", {})
    assert results == ["blocker"]
    assert result.cancelled is True
    assert result.delivered == 1


# --- once() ---

@pytest.mark.asyncio
async def test_once_auto_unsubscribes_after_first_call():
    bus = EventBus()
    call_count = 0

    async def handler(payload):
        nonlocal call_count
        call_count += 1

    bus.once("test", handler)

    await bus.emit("test", {})
    await bus.emit("test", {})
    assert call_count == 1


# --- wait_for() ---

@pytest.mark.asyncio
async def test_wait_for_resolves_on_next_emit():
    bus = EventBus()

    async def emitter():
        await asyncio.sleep(0.05)
        await bus.emit("test", {"value": 42})

    asyncio.ensure_future(emitter())
    payload = await bus.wait_for("test", timeout=1.0)
    assert payload == {"value": 42}


@pytest.mark.asyncio
async def test_wait_for_timeout():
    bus = EventBus()
    with pytest.raises(asyncio.TimeoutError):
        await bus.wait_for("test", timeout=0.05)


# --- Event history ---

@pytest.mark.asyncio
async def test_event_history_tracking():
    bus = EventBus(max_history=3)

    await bus.emit("a", 1)
    await bus.emit("b", 2)
    await bus.emit("c", 3)
    await bus.emit("d", 4)  # should evict "a"

    history = bus.get_history()
    assert len(history) == 3
    assert history[0] == ("b", 2)
    assert history[1] == ("c", 3)
    assert history[2] == ("d", 4)


@pytest.mark.asyncio
async def test_event_history_disabled_by_default():
    bus = EventBus()
    await bus.emit("test", {})
    assert bus.get_history() == []


# --- list_subscribers() ---

@pytest.mark.asyncio
async def test_list_subscribers():
    bus = EventBus()

    async def handler_a(payload):
        pass

    async def handler_b(payload):
        pass

    bus.subscribe("test", handler_a, priority=0, name="safety_check")
    bus.subscribe("test", handler_b, priority=100)

    subs = bus.list_subscribers("test")
    assert len(subs) == 2
    assert subs[0]["priority"] == 0
    assert subs[0]["name"] == "safety_check"
    assert subs[1]["priority"] == 100


# --- EventResult structure ---

@pytest.mark.asyncio
async def test_emit_returns_event_result():
    bus = EventBus()
    result = await bus.emit("nonexistent", {})
    assert isinstance(result, EventResult)
    assert result.delivered == 0
    assert result.cancelled is False
    assert result.errors == []


# --- Unsubscribe ---

@pytest.mark.asyncio
async def test_unsubscribe_removes_callback():
    bus = EventBus()
    results = []

    async def handler(payload):
        results.append("called")

    bus.subscribe("test", handler)
    await bus.emit("test", {})
    assert results == ["called"]

    bus.unsubscribe("test", handler)
    await bus.emit("test", {})
    assert results == ["called"]  # not called again


# --- Typed Event enum values ---

def test_event_enum_values():
    assert Event.TURN_START == "turn_start"
    assert Event.TURN_END == "turn_end"
    assert Event.AGENT_START == "agent_start"
    assert Event.AGENT_CHUNK == "agent_chunk"
    assert Event.AGENT_END == "agent_end"
    assert Event.KAIROS_INTERRUPT == "kairos_interrupt"
    assert Event.MEMORY_UPDATE == "memory_update"
