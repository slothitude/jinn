import asyncio
from typing import AsyncGenerator

from src.agents.base import BaseAgent
from src.core.bus import EventBus
from src.core.models import Event


class BuddyAgent(BaseAgent):
    """Collaborative engineering assistant — default agent for code tasks."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__("BUDDY", bus)
        self._interrupted = False

    async def execute(self, prompt: str) -> AsyncGenerator[str, None]:
        self._interrupted = False
        await self.bus.emit(Event.AGENT_START, {"agent": self.name})

        try:
            async for token in self.stream_llm(prompt):
                if self._interrupted:
                    yield "\n[INTERRUPTED]"
                    break
                yield token
                await self.bus.emit(Event.AGENT_CHUNK, {"agent": self.name, "chunk": token})
        except Exception:
            # Fallback to echo-based simulation if LLM is unavailable
            response = f"[{self.name}] Processing: {prompt}"
            for chunk in response.split(" "):
                if self._interrupted:
                    yield "\n[INTERRUPTED]"
                    break
                await asyncio.sleep(0.02)
                token = chunk + " "
                yield token
                await self.bus.emit(Event.AGENT_CHUNK, {"agent": self.name, "chunk": token})

        await self.bus.emit(Event.AGENT_END, {"agent": self.name})

    async def steer(self, message: str) -> None:
        self._interrupted = True
        await self.bus.emit(Event.KAIROS_INTERRUPT, {"target": self.name, "message": message})
