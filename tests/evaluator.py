"""Shared test infrastructure for recursive stress tests.

Provides isolated system wiring with real LLM (glm-5-turbo) and helpers
for injecting memories, asserting traces, and creating test clients.
"""

import tempfile
from typing import List

from openai import AsyncOpenAI

from src.agents.buddy import BuddyAgent
from src.agents.kairos import KairosAgent
from src.agents.ultraplan import UltraplanAgent
from src.core.bus import EventBus
from src.core.models import AgentState, AgentRequest
from src.core.provider import LLMConfig, create_client
from src.core.query_engine import QueryEngine
from src.core.registry import wire
from src.feedback.observability import register_feedback_hooks
from src.feedback.trace_logger import DecisionTrace, TraceLogger
from src.memory.retrieval import retrieve
from src.memory.schema import MemoryUnit
from src.memory.store import MemoryStore

TEST_MODEL = "glm-5-turbo"


def create_test_client() -> AsyncOpenAI:
    """Create an AsyncOpenAI client using .env config."""
    return create_client(LLMConfig(
        base_url=__import__("os").getenv("LLM_BASE_URL", ""),
        api_key=__import__("os").getenv("LLM_API_KEY", ""),
        model=TEST_MODEL,
    ))


def create_test_system():
    """Wire an isolated test system with real LLM.

    Returns (bus, engine, store, trace_logger, tmpfiles) where tmpfiles
    is a list of temp paths to clean up after tests.
    """
    tmpfiles = []
    mem_path = tempfile.mktemp(suffix=".db")
    trace_path = tempfile.mktemp(suffix=".db")
    tmpfiles.extend([mem_path, trace_path])

    bus = EventBus()
    store = MemoryStore(db_path=mem_path)
    trace_logger = TraceLogger(db_path=trace_path)
    register_feedback_hooks(bus, trace_logger)

    engine = QueryEngine(bus)
    buddy = BuddyAgent(bus)
    kairos = KairosAgent(bus)
    ultraplan = UltraplanAgent(bus)
    wire(bus, buddy, kairos, ultraplan)
    engine.register_agent(buddy)
    engine.register_agent(kairos)
    engine.register_agent(ultraplan)
    engine.memory_retriever = lambda q, strategy: retrieve(q, strategy, store)

    return bus, engine, store, trace_logger, tmpfiles


def inject_memories(store: MemoryStore, memories: List[MemoryUnit]) -> None:
    """Batch-insert MemoryUnit records into the store."""
    for m in memories:
        store.put(m)


def assert_trace_matches(
    trace: DecisionTrace,
    expected_agent: str,
    expected_outcome: str = "success",
) -> None:
    """Validate a DecisionTrace against expected routing."""
    assert trace.policy_decision.get("agent") == expected_agent, (
        f"Expected agent={expected_agent}, got {trace.policy_decision.get('agent')}"
    )
    assert trace.outcome == expected_outcome, (
        f"Expected outcome={expected_outcome}, got {trace.outcome}"
    )
