from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.bus import EventBus

_SUB_ATTR = "_eventbus_subscriptions"


def listens(event_type: str, priority: int = 50):
    """Decorator that stamps subscription metadata on a method."""
    def decorator(method):
        subs = getattr(method, _SUB_ATTR, [])
        subs.append((event_type, priority))
        setattr(method, _SUB_ATTR, subs)
        return method
    return decorator


def wire(bus: EventBus, *components) -> int:
    """Scan components for @listens-decorated methods, subscribe them."""
    count = 0
    for component in components:
        for attr_name in dir(component):
            method = getattr(component, attr_name, None)
            if method is None:
                continue
            subs = getattr(method, _SUB_ATTR, None)
            if subs:
                for event_type, priority in subs:
                    bus.subscribe(event_type, method, priority=priority)
                    count += 1
    return count
