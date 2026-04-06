import asyncio
from typing import AsyncGenerator

from src.agents.base import BaseAgent
from src.core.bus import EventBus
from src.core.models import Event


class KairosAgent(BaseAgent):
    """Interrupt-driven monitoring agent — watches executions, intervenes on anomalies."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__("KAIROS", bus)
        self._anomaly_keywords = {"error", "timeout", "forbidden", "unsafe", "exception"}

    async def execute(self, prompt: str) -> AsyncGenerator[str, None]:
        await self.bus.emit(Event.AGENT_START, {"agent": self.name})

        response = f"[{self.name}] Monitoring active. No anomalies detected."
        for chunk in response.split(" "):
            await asyncio.sleep(0.02)
            token = chunk + " "
            yield token
            await self.bus.emit(Event.AGENT_CHUNK, {"agent": self.name, "chunk": token})

        await self.bus.emit(Event.AGENT_END, {"agent": self.name})

    def detect_anomaly(self, payload: dict) -> bool:
        chunk = payload.get("chunk", "").lower()
        return any(kw in chunk for kw in self._anomaly_keywords)

    async def on_agent_chunk(self, payload: dict) -> None:
        """EventBus subscriber — monitors other agents' output for anomalies."""
        if self.detect_anomaly(payload):
            await self.bus.emit(
                Event.KAIROS_INTERRUPT,
                {"source": self.name, "anomaly": payload["chunk"]},
            )
