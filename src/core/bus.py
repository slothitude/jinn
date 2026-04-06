import asyncio
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from src.core.models import EventCancelled, EventResult


class EventBus:
    """Reactive backbone with priority-based execution.

    Lower priority numbers run first. Safety filters at 0, core logic at 50,
    observers/loggers at 100.

    Features:
    - Error isolation: one failing subscriber doesn't crash others
    - Cancellation: raise EventCancelled to stop propagation
    - once() / wait_for(): single-fire and awaitable subscriptions
    - History: optional rolling buffer of recent events
    - Subscriber metadata: list_subscribers() for introspection
    """

    def __init__(self, max_history: int = 0) -> None:
        self._subscribers: Dict[str, List[Tuple[int, Callable, Optional[str]]]] = {}
        self._history: Optional[Deque[Tuple[str, Any]]] = (
            deque(maxlen=max_history) if max_history > 0 else None
        )
        # For wait_for: map event_type -> list of Futures to resolve
        self._waiters: Dict[str, List[asyncio.Future]] = {}

    def subscribe(
        self, event_type: str, callback: Callable, priority: int = 50, name: Optional[str] = None
    ) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        sub_name = name or getattr(callback, "__name__", repr(callback))
        self._subscribers[event_type].append((priority, callback, sub_name))
        self._subscribers[event_type].sort(key=lambda x: x[0])

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                (p, cb, n) for p, cb, n in self._subscribers[event_type] if cb is not callback
            ]

    def once(self, event_type: str, callback: Callable, priority: int = 50) -> None:
        """Subscribe to the next occurrence of event_type, then auto-unsubscribe."""

        async def _wrapper(payload: Any) -> None:
            self.unsubscribe(event_type, _wrapper)
            await callback(payload)

        # Carry the original name for introspection
        _wrapper.__name__ = f"once({getattr(callback, '__name__', repr(callback))})"
        self.subscribe(event_type, _wrapper, priority)

    def wait_for(self, event_type: str, timeout: Optional[float] = None) -> asyncio.Future:
        """Return a Future that resolves with the next payload for event_type.

        Raises asyncio.TimeoutError if timeout is provided and exceeded.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        if timeout is not None:

            async def _timeout_guard():
                await asyncio.sleep(timeout)
                if not future.done():
                    future.set_exception(asyncio.TimeoutError())
                    self._remove_waiter(event_type, future)

            asyncio.ensure_future(_timeout_guard())

        if event_type not in self._waiters:
            self._waiters[event_type] = []
        self._waiters[event_type].append(future)
        return future

    async def emit(self, event_type: str, payload: Any = None) -> EventResult:
        """Emit an event to all subscribers in priority order.

        Returns EventResult with delivery count, cancellation flag, and errors.
        A subscriber raising EventCancelled stops propagation to lower-priority
        subscribers (higher priority numbers).
        """
        # Record history
        if self._history is not None:
            self._history.append((event_type, payload))

        # Resolve wait_for futures
        if event_type in self._waiters:
            for future in self._waiters.pop(event_type):
                if not future.done():
                    future.set_result(payload)

        delivered = 0
        cancelled = False
        errors: List[Exception] = []

        if event_type not in self._subscribers:
            return EventResult(delivered=delivered, cancelled=cancelled, errors=errors)

        for _, callback, _ in self._subscribers[event_type]:
            try:
                await callback(payload)
                delivered += 1
            except EventCancelled:
                delivered += 1
                cancelled = True
                break
            except Exception as exc:
                errors.append(exc)

        return EventResult(delivered=delivered, cancelled=cancelled, errors=errors)

    def list_subscribers(self, event_type: str) -> List[Dict[str, Any]]:
        """Return metadata for all subscribers of an event type."""
        subs = self._subscribers.get(event_type, [])
        return [
            {"priority": priority, "name": name, "callback": callback}
            for priority, callback, name in subs
        ]

    def get_history(self) -> List[Tuple[str, Any]]:
        """Return a snapshot of the event history (empty if max_history=0)."""
        if self._history is None:
            return []
        return list(self._history)

    def _remove_waiter(self, event_type: str, future: asyncio.Future) -> None:
        waiters = self._waiters.get(event_type)
        if waiters:
            self._waiters[event_type] = [f for f in waiters if f is not future]
