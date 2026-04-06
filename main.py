import asyncio
import sys

from src.core.bus import EventBus
from src.core.models import AgentRequest, AgentState, Event
from src.core.query_engine import QueryEngine
from src.agents.buddy import BuddyAgent
from src.agents.kairos import KairosAgent
from src.agents.ultraplan import UltraplanAgent
from src.execution.toolbox import ToolExecutor
from src.memory.store import MemoryStore
from src.memory.retrieval import retrieve as memory_retrieve
from src.memory.autodream import AutoDream
from src.feedback.trace_logger import TraceLogger
from src.feedback.observability import register_feedback_hooks


async def main() -> None:
    # L2: EventBus
    bus = EventBus()

    # L4: Memory
    store = MemoryStore()
    autodream = AutoDream(bus, store)

    # L6: Agents
    buddy = BuddyAgent(bus)
    kairos = KairosAgent(bus)
    ultraplan = UltraplanAgent(bus)

    # Wire KAIROS as monitor on other agents' output
    bus.subscribe(Event.AGENT_CHUNK, kairos.on_agent_chunk, priority=10)

    # L7: Tool Execution
    tool_executor = ToolExecutor(bus)
    buddy.set_tool_executor(tool_executor)

    # L8: Feedback
    trace_logger = TraceLogger()
    register_feedback_hooks(bus, trace_logger)

    # L3-L7: QueryEngine orchestrator
    engine = QueryEngine(bus)
    engine.register_agent(buddy)
    engine.register_agent(kairos)
    engine.register_agent(ultraplan)
    engine.memory_retriever = lambda q, strategy: memory_retrieve(q, strategy, store)

    # Session state
    state = AgentState(session_id="cli-session-001")

    print("=== JINN — Programmable Cognition System ===")
    print("Type your input (or 'quit' to exit):\n")

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        if not user_input:
            continue

        request = AgentRequest(session_id=state.session_id, input_text=user_input)
        response = await engine.process(request, state)
        print(f"\n{response}\n")

    # Cleanup
    store.close()
    trace_logger.close()


if __name__ == "__main__":
    asyncio.run(main())
