"""Tests for JINN lifecycle: names, crypt, and grim reaper."""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.memory.names import assign_name, _reset, _NAMES
from src.memory.crypt import CryptEntry, CryptStore
from src.memory.schema import MemoryUnit
from src.memory.store import MemoryStore
from src.core.bus import EventBus
from src.core.models import Event
from src.core.reaper import GrimReaper


# ── Names ──────────────────────────────────────────────────────────────────


def test_assign_name_returns_from_list():
    _reset()
    name = assign_name()
    assert name in _NAMES


def test_assign_name_unique():
    _reset()
    names = [assign_name() for _ in range(20)]
    assert len(names) == len(set(names))


# ── Crypt Store ────────────────────────────────────────────────────────────


class TestCryptStore:
    def setup_method(self):
        self.store = CryptStore(db_path=Path("data/test_crypt.db"))

    def teardown_method(self):
        self.store.close()
        Path("data/test_crypt.db").unlink(missing_ok=True)

    def test_crypt_store_crud(self):
        entry = CryptEntry(
            name="Zephyr",
            role="WORKER",
            born_at=time.time(),
            task_summary="Refactor the authentication module",
            lessons=["Always validate tokens before decoding"],
        )
        self.store.put(entry)

        results = self.store.get_by_name("Zephyr")
        assert len(results) >= 1
        assert results[0].name == "Zephyr"
        assert results[0].task_summary == "Refactor the authentication module"
        assert "Always validate tokens before decoding" in results[0].lessons

    def test_crypt_recent_lessons(self):
        for i in range(3):
            entry = CryptEntry(
                name=f"JINN-{i}",
                role="WORKER",
                born_at=time.time() - 100 + i,
                died_at=time.time() - 50 + i,
                task_summary=f"Task {i}",
                lessons=[f"Lesson {i}: always use async"],
            )
            self.store.put(entry)

        lessons = self.store.get_recent_lessons(limit=10)
        assert len(lessons) >= 3
        # Most recent first
        assert "Lesson 2" in lessons[0]

    def test_crypt_search_lessons(self):
        entry = CryptEntry(
            name="Aether",
            role="WORKER",
            born_at=time.time(),
            task_summary="Implement authentication with JWT tokens",
            lessons=["Validate JWT expiry before processing requests"],
        )
        self.store.put(entry)

        results = self.store.search_lessons("authentication JWT", limit=10)
        assert len(results) >= 1
        assert "JWT" in results[0]

    def test_crypt_search_lessons_empty_query(self):
        entry = CryptEntry(
            name="Calypso",
            role="WORKER",
            born_at=time.time(),
            task_summary="Test task",
            lessons=["Test lesson"],
        )
        self.store.put(entry)

        results = self.store.search_lessons("", limit=10)
        assert len(results) >= 1


# ── Grim Reaper ────────────────────────────────────────────────────────────


class TestGrimReaper:
    def setup_method(self):
        self.bus = EventBus()
        self.crypt_store = CryptStore(db_path=Path("data/test_crypt.db"))
        self.memory_store = MemoryStore(db_path=Path("data/test_memory.db"))
        self.reaper = GrimReaper(self.bus, self.crypt_store, self.memory_store)
        # Wire subscriptions manually
        from src.core.registry import wire
        wire(self.bus, self.reaper)

    def teardown_method(self):
        self.crypt_store.close()
        self.memory_store.close()
        Path("data/test_crypt.db").unlink(missing_ok=True)
        Path("data/test_memory.db").unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_reaper_records_in_crypt(self):
        await self.bus.emit(Event.DELEGATION_END, {
            "task": "Refactor the authentication module to use JWT tokens",
            "tier": "SUPERVISOR",
            "index": 0,
            "success": True,
            "session_id": "test-session-1",
            "jinn_name": "Zephyr",
            "born_at": time.time() - 10,
            "provider": "zhipu",
        })

        entries = self.crypt_store.get_by_name("Zephyr")
        assert len(entries) >= 1
        assert entries[0].role == "SUPERVISOR"
        assert entries[0].outcome == "success"

    @pytest.mark.asyncio
    async def test_reaper_stores_lessons(self):
        # Mock LLM autopsy to return lessons
        with patch.object(self.reaper, "_autopsy", new_callable=AsyncMock) as mock_autopsy:
            mock_autopsy.return_value = [
                "Always validate input before processing",
                "Use async I/O for file reads",
            ]

            await self.bus.emit(Event.DELEGATION_END, {
                "task": "Build a comprehensive REST API with authentication, validation, "
                        "and error handling for the user management module",
                "tier": "WORKER",
                "index": 0,
                "success": True,
                "session_id": "test-session-2",
                "jinn_name": "Aether",
                "born_at": time.time() - 10,
                "provider": "nvidia",
            })

        # Check memory store has lesson-tagged units
        lessons = self.memory_store.search_by_tag("lesson")
        assert len(lessons) >= 1
        assert any("validate input" in (l.prompt_fragment or "") for l in lessons)

    @pytest.mark.asyncio
    async def test_reaper_handles_llm_failure(self):
        with patch.object(self.reaper, "_autopsy", new_callable=AsyncMock) as mock_autopsy:
            mock_autopsy.side_effect = Exception("LLM unavailable")

            # Should not crash
            await self.bus.emit(Event.DELEGATION_END, {
                "task": "A sufficiently long task description that exceeds fifty characters "
                        "to trigger the autopsy pathway in the grim reaper",
                "tier": "WORKER",
                "index": 0,
                "success": False,
                "session_id": "test-session-3",
                "jinn_name": "Halcyon",
                "born_at": time.time() - 10,
                "provider": "zhipu",
            })

        # Crypt entry should still exist (recorded before autopsy)
        entries = self.crypt_store.get_by_name("Halcyon")
        assert len(entries) >= 1
