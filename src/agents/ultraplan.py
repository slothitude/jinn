import asyncio
from typing import AsyncGenerator

from src.agents.base import BaseAgent
from src.core.bus import EventBus


class UltraplanAgent(BaseAgent):
    """Heavy planning agent — decomposes tasks, estimates costs before execution."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__("ULTRAPLAN", bus)

    async def execute(self, prompt: str) -> AsyncGenerator[str, None]:
        await self.bus.emit("agent_start", {"agent": self.name})

        plan_steps = [
            "[ULTRAPLAN] Analyzing task...",
            " Decomposing into subtasks...",
            " Estimating costs...",
            " Generating execution plan.",
        ]
        for step in plan_steps:
            await asyncio.sleep(0.05)
            yield step
            await self.bus.emit("agent_chunk", {"agent": self.name, "chunk": step})

        await self.bus.emit("agent_end", {"agent": self.name})

    async def estimate_cost(self, subtasks: list[str]) -> float:
        """Estimate total cost of a plan based on subtask count."""
        return len(subtasks) * 0.5  # placeholder cost model
