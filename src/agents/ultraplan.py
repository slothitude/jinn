import asyncio
from typing import AsyncGenerator

from src.agents.base import BaseAgent
from src.core.bus import EventBus
from src.core.models import Event


class UltraplanAgent(BaseAgent):
    """Heavy planning agent — decomposes tasks, estimates costs before execution."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__("ULTRAPLAN", bus)

    async def execute(self, prompt: str) -> AsyncGenerator[str, None]:
        await self.bus.emit(Event.AGENT_START, {"agent": self.name})

        try:
            async for token in self.stream_llm(
                prompt, system="You are a planning agent. Decompose tasks into actionable steps."
            ):
                yield token
                await self.bus.emit(Event.AGENT_CHUNK, {"agent": self.name, "chunk": token})
        except Exception:
            # Fallback to mock steps if LLM is unavailable
            plan_steps = [
                "[ULTRAPLAN] Analyzing task...",
                " Decomposing into subtasks...",
                " Estimating costs...",
                " Generating execution plan.",
            ]
            for step in plan_steps:
                await asyncio.sleep(0.05)
                yield step
                await self.bus.emit(Event.AGENT_CHUNK, {"agent": self.name, "chunk": step})

        await self.bus.emit(Event.AGENT_END, {"agent": self.name})

    async def estimate_cost(self, subtasks: list[str]) -> float:
        """Estimate total cost of a plan based on subtask count."""
        return len(subtasks) * 0.5  # placeholder cost model
