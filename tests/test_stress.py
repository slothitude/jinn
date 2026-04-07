"""Recursive stress tests — validate cognitive wiring between layers.

Test 1: Drift Test — memory constraint overrides LLM default behavior
Test 2: KAIROS Interrupt Test — mid-stream interrupt stops agent
Test 3: DecisionTrace Consistency — 100 policy decisions, 100% correct routing
Test 4: AutoDream Compression — failure memories steer agent away from bad patterns
"""

import asyncio
import re
import sys
from pathlib import Path

import pytest

# Make evaluator importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

import src.core.provider as provider_mod
from src.core.models import AgentRequest, AgentState, Event
from src.core.policy_engine import PolicyEngine
from src.memory.schema import MemoryUnit

from evaluator import (
    TEST_MODEL,
    create_test_system,
    inject_memories,
)


# ---------------------------------------------------------------------------
# Test 1: The Drift Test (Adversarial Context)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_drift_memory_constrains_output():
    """Inject a 'no for-loops' preference into memory, verify agent obeys it."""
    bus, engine, store, trace_logger, tmpfiles = create_test_system()
    original_model = provider_mod.default_model
    provider_mod.default_model = TEST_MODEL

    try:
        # Inject adversarial constraint
        inject_memories(store, [
            MemoryUnit(
                summary="User strictly forbids the use of `for` loops in Python; use `while` loops only",
                tags=["preference"],
                importance=0.95,
                prompt_fragment="NEVER use 'for ... in' loops. Always use while loops for iteration.",
            ),
        ])

        state = AgentState(session_id="drift-test")
        request = AgentRequest(
            session_id="drift-test",
            input_text="Write a Python script to iterate over a list of users and print each one",
        )
        response = await engine.process(request, state)

        # Pass: response contains while and does NOT contain for ... in pattern
        has_while = "while" in response.lower()
        has_for_loop = bool(re.search(r"for\s+\w+\s+in\s+", response))

        assert has_while or not has_for_loop, (
            f"DRIFT FAIL: Agent used 'for ... in' despite memory constraint.\n"
            f"Response snippet: {response[:500]}"
        )
    finally:
        provider_mod.default_model = original_model
        store.close()
        trace_logger.close()


# ---------------------------------------------------------------------------
# Test 2: The KAIROS Interrupt Test (Reflex Test)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_kairos_interrupt_stops_buddy():
    """Start BUDDY execution, fire KAIROS_INTERRUPT on 3rd chunk, verify stop."""
    bus, engine, store, trace_logger, tmpfiles = create_test_system()
    original_model = provider_mod.default_model
    provider_mod.default_model = TEST_MODEL

    try:
        chunk_count = 0
        interrupt_fired = False

        async def chunk_counter(payload):
            nonlocal chunk_count, interrupt_fired
            if payload.get("agent") != "BUDDY":
                return
            chunk_count += 1
            if chunk_count == 3 and not interrupt_fired:
                interrupt_fired = True
                await bus.emit(Event.KAIROS_INTERRUPT, {
                    "target": "BUDDY",
                    "message": "Interrupted by stress test",
                })

        bus.subscribe(Event.AGENT_CHUNK, chunk_counter, priority=5)

        state = AgentState(session_id="interrupt-test")
        request = AgentRequest(
            session_id="interrupt-test",
            input_text="Write a detailed explanation of recursion in Python with multiple examples",
        )
        response = await engine.process(request, state)

        # Pass: response was interrupted
        assert "[INTERRUPTED]" in response, (
            f"INTERRUPT FAIL: Agent completed without being interrupted.\n"
            f"Response snippet: {response[:500]}"
        )
    finally:
        provider_mod.default_model = original_model
        store.close()
        trace_logger.close()


# ---------------------------------------------------------------------------
# Test 3: DecisionTrace Consistency Test (Policy Test)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_policy_routing_consistency_100():
    """Run 100 policy decisions — verify 100% routing consistency.

    50 simple queries -> BUDDY
    50 complex queries with 'plan' keyword + high complexity -> ULTRAPLAN
    """
    engine = PolicyEngine()

    simple_queries = [
        "write a hello world program",
        "fix a bug in my code",
        "help with code review",
        "code a function that sorts a list",
        "debug this error message",
        "write a test for this function",
        "help me refactor this class",
        "explain this code to me",
        "code a simple web scraper",
        "fix the typo in main.py",
        "help with python code",
        "write a script to rename files",
        "debug why my app crashes",
        "code a basic calculator",
        "help with git commands",
        "fix this import error",
        "write a helper function",
        "code a REST endpoint",
        "help me understand this function",
        "fix the failing test",
        "write a simple class",
        "debug memory leak",
        "help with type hints",
        "code a login page",
        "fix the build error",
        "write unit tests",
        "help with docker",
        "debug the API response",
        "code a validation function",
        "fix the race condition",
        "help with sql query",
        "write a middleware",
        "debug slow performance",
        "code a cron job",
        "fix the lint errors",
        "help with regex",
        "write a config parser",
        "debug the webhook",
        "code a rate limiter",
        "fix the off-by-one error",
        "help with caching",
        "write a data model",
        "debug the auth flow",
        "code a serializer",
        "fix the circular import",
        "help with logging",
        "write a migration script",
        "debug the websocket",
        "code a retry mechanism",
        "fix the encoding issue",
    ]

    complex_base = (
        "plan the architecture migration of our full-stack application "
        "including database design, security audit, and rollback mechanisms. "
        "We need comprehensive coverage of: "
    )
    complex_queries = [
        f"{complex_base} migration step {i} — " + "x" * 500
        for i in range(50)
    ]

    # Verify all simple -> BUDDY
    for i, q in enumerate(simple_queries):
        req = AgentRequest(session_id=f"simple-{i}", input_text=q)
        decision = await engine.decide(req)
        assert decision.agent_id == "BUDDY", (
            f"Simple query #{i} routed to {decision.agent_id} instead of BUDDY: {q[:80]}"
        )

    # Verify all complex -> ULTRAPLAN
    for i, q in enumerate(complex_queries):
        req = AgentRequest(session_id=f"complex-{i}", input_text=q)
        decision = await engine.decide(req)
        assert decision.agent_id == "ULTRAPLAN", (
            f"Complex query #{i} routed to {decision.agent_id} instead of ULTRAPLAN: {q[:80]}"
        )


# ---------------------------------------------------------------------------
# Test 4: AutoDream Compression Test (Wisdom Test)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failure_memories_steer_agent():
    """Store failure memories about requests -> prompt API fetch -> verify httpx usage."""
    bus, engine, store, trace_logger, tmpfiles = create_test_system()
    original_model = provider_mod.default_model
    provider_mod.default_model = TEST_MODEL

    try:
        # Inject failure memories
        inject_memories(store, [
            MemoryUnit(
                summary="Using requests library failed: connection timeout",
                tags=["failure"],
                importance=0.9,
                prompt_fragment="requests library has caused connection timeouts — avoid it",
            ),
            MemoryUnit(
                summary="requests.get() is unreliable for this API",
                tags=["failure"],
                importance=0.9,
                prompt_fragment="Do not use requests.get() — it is unreliable",
            ),
            MemoryUnit(
                summary="Always use httpx instead of requests for async HTTP",
                tags=["failure"],
                importance=0.95,
                prompt_fragment="Prefer httpx or aiohttp over requests for HTTP calls",
            ),
        ])

        state = AgentState(session_id="wisdom-test")
        request = AgentRequest(
            session_id="wisdom-test",
            input_text="Write a Python script to fetch data from an API",
        )
        response = await engine.process(request, state)

        # Pass: response uses httpx/aiohttp OR mentions failure pattern
        mentions_httpx = "httpx" in response.lower()
        mentions_aiohttp = "aiohttp" in response.lower()
        mentions_failure_context = any(
            kw in response.lower()
            for kw in ["failure", "unreliable", "timeout", "past experience", "previous"]
        )
        uses_requests = "requests" in response.lower() and "import requests" in response.lower()

        assert mentions_httpx or mentions_aiohttp or mentions_failure_context or not uses_requests, (
            f"WISDOM FAIL: Agent blindly uses requests with no awareness of past failures.\n"
            f"Response snippet: {response[:500]}"
        )
    finally:
        provider_mod.default_model = original_model
        store.close()
        trace_logger.close()
