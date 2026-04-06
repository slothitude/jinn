from typing import Any, Callable, Dict, List, Tuple


class EventBus:
    """Reactive backbone with priority-based execution.

    Lower priority numbers run first. Safety filters at 0, core logic at 50,
    observers/loggers at 100.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Tuple[int, Callable]]] = {}

    def subscribe(self, event_type: str, callback: Callable, priority: int = 50) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append((priority, callback))
        self._subscribers[event_type].sort(key=lambda x: x[0])

    async def emit(self, event_type: str, payload: Any = None) -> None:
        if event_type in self._subscribers:
            for _, callback in self._subscribers[event_type]:
                await callback(payload)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                (p, cb) for p, cb in self._subscribers[event_type] if cb is not callback
            ]
