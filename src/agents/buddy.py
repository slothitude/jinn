import asyncio
from typing import AsyncGenerator

from src.agents.base import BaseAgent
from src.core.bus import EventBus


class BuddyAgent(BaseAgent):
    """Collaborative engineering assistant — default agent for code tasks."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__("BUDDY", bus)
        self._interrupted = False

    async def execute(self, prompt: str) -> AsyncGenerator[str, None]:
        self._interrupted = False
        await self.bus.emit("agent_start", {"agent": self.name})

        # In production: stream from LLM via provider
        # For now: echo-based simulation
        response = f"[{self.name}] Processing: {prompt}"
        chunks = response.split(" ")

        for chunk in chunks:
            if self._interrupted:
                yield "\n[INTERRUPTED]"
                break
            await asyncio.sleep(0.02)
            token = chunk + " "
            yield token
            await self.bus.emit("agent_chunk", {"agent": self.name, "chunk": token})

        await self.bus.emit("agent_end", {"agent": self.name})

    async def steer(self, message: str) -> None:
        self._interrupted = True
        await self.bus.emit("kairos_interrupt", {"target": self.name, "message": message})
