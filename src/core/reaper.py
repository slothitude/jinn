"""The Grim Reaper — performs autopsy on deceased delegated workers."""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from src.core.bus import EventBus
from src.core.models import Event
from src.core.registry import listens
from src.memory.crypt import CryptEntry, CryptStore
from src.memory.schema import MemoryUnit
from src.memory.store import MemoryStore

# Lazy import for provider to avoid circular deps at module level


class GrimReaper:
    """Listens for DELEGATION_END, records workers in the crypt, extracts lessons via LLM."""

    def __init__(
        self,
        bus: EventBus,
        crypt_store: CryptStore,
        memory_store: MemoryStore,
    ) -> None:
        self.bus = bus
        self.crypt_store = crypt_store
        self.memory_store = memory_store

    @listens(Event.DELEGATION_END, priority=85)
    async def on_delegation_end(self, payload: dict) -> None:
        """Record deceased worker in crypt, run LLM autopsy, store lessons."""
        name = payload.get("jinn_name", "Unknown")
        role = payload.get("tier", "WORKER")
        task = payload.get("task", "")
        success = payload.get("success", False)
        provider = payload.get("provider", "")
        born_at = payload.get("born_at", time.time())
        session_id = payload.get("session_id", "")

        # Record in crypt
        entry = CryptEntry(
            name=name,
            role=role,
            provider=provider,
            born_at=born_at,
            died_at=time.time(),
            task_summary=task[:500],
            outcome="success" if success else "failure",
        )
        self.crypt_store.put(entry)

        # Skip autopsy for trivial tasks
        if len(task) < 50:
            return

        # LLM autopsy — extract lessons
        lessons = await self._autopsy(task, success, name, role)
        if not lessons:
            return

        # Store lessons in crypt entry
        entry.lessons = lessons
        self.crypt_store.put(entry)

        # Store lessons as MemoryUnits (dedup like AutoDream)
        await self._store_lessons(lessons, role)

    async def _autopsy(
        self, task: str, success: bool, name: str, role: str
    ) -> list[str]:
        """Use LLM to extract lessons from the completed task."""
        try:
            from src.core.provider import _load_config, _httpx_chat
            config = _load_config()
        except Exception:
            return []

        prompt = (
            f"Analyze this completed task by a JINN worker named '{name}' (role: {role}).\n"
            f"Task: {task[:1000]}\n"
            f"Outcome: {'success' if success else 'failure'}\n\n"
            f"Extract up to 5 concise one-sentence lessons learned. "
            f"Return ONLY a JSON array of strings, no other text.\n"
            f'Example: ["Always validate input before processing", "Use async I/O for file reads"]'
        )

        try:
            result = await _httpx_chat(
                config.base_url,
                config.api_key,
                config.model,
                [{"role": "user", "content": prompt}],
                timeout=30.0,
            )
            # Parse JSON array from response
            lessons = json.loads(result.strip())
            if isinstance(lessons, list):
                return [str(l).strip() for l in lessons if str(l).strip()]
        except Exception:
            pass

        return []

    async def _store_lessons(self, lessons: list[str], role: str) -> None:
        """Store lessons as MemoryUnits with dedup."""
        existing = self.memory_store.search_by_tag("lesson")
        existing_fragments = {m.prompt_fragment for m in existing if m.prompt_fragment}

        for lesson in lessons:
            if lesson in existing_fragments:
                continue
            unit = MemoryUnit(
                summary=f"Lesson from {role}: {lesson[:200]}",
                tags=["lesson", role.lower()],
                importance=0.6,
                prompt_fragment=lesson,
            )
            self.memory_store.put(unit)
            existing_fragments.add(lesson)
