import time
from typing import List, Optional

from src.core.bus import EventBus
from src.memory.schema import MemoryUnit
from src.memory.store import MemoryStore


class AutoDream:
    """Background compression loop — consolidates session history into memory.

    Subscribes to agent_end events. When fired:
    1. Orient: Analyze session for salient information
    2. Gather: Extract candidate memory units
    3. Consolidate: Merge with existing memories
    4. Prune: Enforce limits, decay old entries
    5. Fire memory_update event
    """

    MAX_MEMORIES = 500
    DECAY_THRESHOLD = 0.1

    def __init__(self, bus: EventBus, store: MemoryStore) -> None:
        self.bus = bus
        self.store = store
        self.bus.subscribe("agent_end", self.on_agent_end, priority=80)

    async def on_agent_end(self, payload: dict) -> None:
        """Triggered when any agent finishes execution."""
        agent = payload.get("agent", "unknown")
        # In production: LLM-based extraction from conversation
        # For now: stub that creates a basic memory unit
        await self._consolidate(agent)

    async def _consolidate(self, agent: str) -> None:
        """Consolidate session data into structured memory."""
        count = self.store.count()
        if count < self.MAX_MEMORIES:
            return  # No need to compress yet

        all_memories = self.store.get_all(limit=self.MAX_MEMORIES * 2)

        # Prune low-importance, old memories
        pruned = 0
        for m in all_memories:
            age_days = (time.time() - m.last_used) / 86400
            if m.importance < self.DECAY_THRESHOLD and age_days > 7:
                self.store.delete(m.id)
                pruned += 1

        if pruned > 0:
            await self.bus.emit("memory_update", {"pruned": pruned, "remaining": self.store.count()})

    def extract_from_session(self, history: List[dict]) -> List[MemoryUnit]:
        """Extract candidate memory units from conversation history.

        In production, this uses LLM analysis. For now, creates summary units.
        """
        units: list[MemoryUnit] = []
        for entry in history[-5:]:  # Last 5 exchanges
            user_msg = entry.get("user", "")
            if len(user_msg) > 20:  # Only substantive interactions
                units.append(
                    MemoryUnit(
                        summary=user_msg[:200],
                        tags=["preference"],
                        importance=0.6,
                        prompt_fragment=f"User discussed: {user_msg[:100]}",
                    )
                )
        return units
