import asyncio

import pytest

from src.core.bus import EventBus
from src.core.models import Event
from src.core.registry import listens, wire


class TestDecorator:
    def test_decorator_stores_metadata(self):
        @listens("test_event", priority=42)
        async def handler(self, payload):
            pass

        assert hasattr(handler, "_eventbus_subscriptions")
        assert ("test_event", 42) in handler._eventbus_subscriptions

    def test_stacked_decorators(self):
        @listens("event_a", priority=10)
        @listens("event_b", priority=20)
        async def handler(self, payload):
            pass

        subs = handler._eventbus_subscriptions
        assert len(subs) == 2
        assert ("event_a", 10) in subs
        assert ("event_b", 20) in subs


class TestWire:
    async def test_wire_subscribes_to_bus(self):
        bus = EventBus()

        class MyComponent:
            def __init__(self, b):
                self.bus = b
                self.called = False

            @listens("ping", priority=50)
            async def on_ping(self, payload):
                self.called = True

        comp = MyComponent(bus)
        count = wire(bus, comp)
        assert count == 1

        await bus.emit("ping", {})
        assert comp.called

    async def test_wire_multiple_components(self):
        bus = EventBus()

        class CompA:
            def __init__(self, b):
                self.bus = b

            @listens("ev1", priority=50)
            async def on_ev1(self, payload):
                pass

        class CompB:
            def __init__(self, b):
                self.bus = b

            @listens("ev2", priority=50)
            async def on_ev2(self, payload):
                pass

        count = wire(bus, CompA(bus), CompB(bus))
        assert count == 2

    async def test_no_decorator_ignored(self):
        bus = EventBus()

        class Comp:
            def __init__(self, b):
                self.bus = b

            async def plain_method(self, payload):
                pass

        count = wire(bus, Comp(bus))
        assert count == 0

    async def test_wire_returns_count(self):
        bus = EventBus()

        class Comp:
            def __init__(self, b):
                self.bus = b

            @listens("e1", priority=10)
            @listens("e2", priority=20)
            async def multi_handler(self, payload):
                pass

            @listens("e3", priority=30)
            async def single_handler(self, payload):
                pass

        count = wire(bus, Comp(bus))
        assert count == 3

    async def test_backward_compat_manual_subscribe(self):
        """Manual bus.subscribe() still works alongside wire()."""
        bus = EventBus()
        results = []

        class Comp:
            def __init__(self, b):
                self.bus = b
                b.subscribe("manual_event", self.on_manual)

            @listens("wired_event", priority=50)
            async def on_wired(self, payload):
                results.append("wired")

            async def on_manual(self, payload):
                results.append("manual")

        comp = Comp(bus)
        wire(bus, comp)

        await bus.emit("wired_event", {})
        await bus.emit("manual_event", {})

        assert results == ["wired", "manual"]
