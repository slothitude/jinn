from src.core.bus import EventBus
from src.core.models import Event
from src.feedback.trace_logger import DecisionTrace, TraceLogger


_FORBIDDEN_PATTERNS = ["forbidden", "unsafe execution", "inject"]


async def safety_monitor(payload: dict) -> None:
    """Priority 0 — blocks responses containing forbidden content."""
    if not payload or "chunk" not in payload:
        return
    chunk = payload.get("chunk", "").lower()
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern in chunk:
            print(f"\n[SAFETY ALERT] Blocked content containing: {pattern}")
            return


async def metrics_logger(payload: dict) -> None:
    """Priority 100 — pure observation, records agent events."""
    if payload and "agent" in payload:
        print(f"  [METRICS] Agent {payload['agent']} event recorded.")


async def trace_recorder(payload: dict, trace_logger: TraceLogger) -> None:
    """Subscribes to turn_end — finalizes decision trace for the turn."""
    if not payload:
        return
    trace = DecisionTrace(
        session_id=payload.get("session_id", ""),
        outcome=payload.get("outcome", "success"),
        policy_decision={"agent": payload.get("agent", "unknown")},
    )
    trace_logger.record(trace)


def register_feedback_hooks(bus: EventBus, trace_logger: TraceLogger | None = None) -> None:
    """Wire all feedback hooks into the EventBus at appropriate priorities."""
    bus.subscribe(Event.AGENT_CHUNK, safety_monitor, priority=0)
    bus.subscribe(Event.AGENT_END, metrics_logger, priority=100)

    if trace_logger:
        async def _trace_recorder(payload):
            await trace_recorder(payload, trace_logger)
        bus.subscribe(Event.TURN_END, _trace_recorder, priority=50)
