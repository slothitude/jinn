import time
from typing import List, Optional

from src.core.bus import EventBus
from src.core.models import Event
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

    Also subscribes to TOOL_CALL_RESULT to learn from tool failures,
    extracting heuristics that flow back into agent prompts.
    """

    MAX_MEMORIES = 500
    DECAY_THRESHOLD = 0.1

    FAILURE_PATTERNS: list[tuple[str, Optional[str], str, str]] = [
        # (error_substring, tool_name_filter, summary, prompt_fragment)
        ("no such file or directory", "bash",
         "mkdir fails without parent directories",
         "Always use `mkdir -p` to create parent directories automatically."),
        ("permission denied", "bash",
         "Permission denied on file operation",
         "Check permissions with `ls -la` and use `chmod` if appropriate."),
        ("timed out", "bash",
         "Commands timing out",
         "Increase timeout parameter or break into smaller steps."),
        ("command not found", "bash",
         "Command not found in shell",
         "Verify installation with `which <cmd>` before using it."),
        ("file not found", "read",
         "File not found when reading",
         "Verify the file path exists with `ls` before attempting to read."),
        ("path traversal blocked", "write",
         "Path traversal attempt blocked",
         "Always use relative paths within the sandbox directory."),
        ("invalid json", None,
         "Invalid JSON in tool arguments",
         "Ensure all argument values are properly quoted and escaped JSON."),
    ]

    def __init__(self, bus: EventBus, store: MemoryStore) -> None:
        self.bus = bus
        self.store = store
        self._pending_failures: list[dict] = []
        self.bus.subscribe(Event.AGENT_END, self.on_agent_end, priority=80)
        self.bus.subscribe(Event.TOOL_CALL_RESULT, self._on_tool_call_result, priority=90)

    async def _on_tool_call_result(self, payload: dict) -> None:
        """Collect failed tool call results for heuristic extraction."""
        if not payload.get("success", True):
            self._pending_failures.append(payload)

    async def on_agent_end(self, payload: dict) -> None:
        """Triggered when any agent finishes execution."""
        agent = payload.get("agent", "unknown")
        await self._dream_on_failures(agent)
        await self._consolidate(agent)

    async def _dream_on_failures(self, agent: str) -> None:
        """Extract heuristics from collected tool failures and persist them."""
        if not self._pending_failures:
            return

        heuristics = self._extract_heuristics(self._pending_failures)
        stored_count = await self._dedup_and_store(heuristics)
        self._pending_failures.clear()

        if stored_count > 0:
            await self.bus.emit(Event.MEMORY_UPDATE, {
                "source": "autodream",
                "heuristics_stored": stored_count,
                "agent": agent,
            })

    def _extract_heuristics(self, failures: list[dict]) -> list[MemoryUnit]:
        """Map failures to MemoryUnits via rule-based pattern matching."""
        units: list[MemoryUnit] = []
        for failure in failures:
            output = failure.get("output", "")
            tool_name = failure.get("name", "")
            for error_sub, tool_filter, summary, fragment in self.FAILURE_PATTERNS:
                if error_sub in output.lower() and (tool_filter is None or tool_filter == tool_name):
                    units.append(MemoryUnit(
                        summary=summary,
                        tags=["heuristic", "failure"],
                        importance=0.7,
                        prompt_fragment=fragment,
                    ))
                    break  # First matching pattern wins
        return units

    async def _dedup_and_store(self, heuristics: list[MemoryUnit]) -> int:
        """Store heuristics, bumping importance of existing ones.

        Returns count of newly stored heuristics.
        """
        if not heuristics:
            return 0

        existing = self.store.search_by_tag("heuristic")
        existing_summaries = {m.summary: m for m in existing}

        stored = 0
        for unit in heuristics:
            match = existing_summaries.get(unit.summary)
            if match:
                match.importance = min(1.0, match.importance + 0.05)
                match.last_used = time.time()
                match.access_count += 1
                self.store.put(match)
            else:
                self.store.put(unit)
                stored += 1
        return stored

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
            await self.bus.emit(Event.MEMORY_UPDATE, {"pruned": pruned, "remaining": self.store.count()})

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
