from typing import Any, Callable, Coroutine, Dict, Optional

from src.core.bus import EventBus
from src.core.models import AgentRequest, AgentState
from src.core.policy_engine import PolicyEngine
from src.promptos.engine import PromptOS
from src.agents.base import BaseAgent


class QueryEngine:
    """Main orchestrator — wires Policy -> Memory -> PromptOS -> Agent.

    Layers: L3 (Policy) -> L4 (Memory) -> L5 (PromptOS) -> L6-L7 (Agent/Execution)
    """

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self.policy = PolicyEngine()
        self.prompt_os = PromptOS()
        self.agents: Dict[str, BaseAgent] = {}
        self.memory_retriever: Optional[Callable[..., Coroutine]] = None

    def register_agent(self, agent: BaseAgent) -> None:
        self.agents[agent.name] = agent

    async def process(self, request: AgentRequest, state: AgentState) -> str:
        await self.bus.emit("turn_start", {"session_id": request.session_id})

        # L3: Policy decision
        decision = await self.policy.decide(request)

        # L4: Memory retrieval — stub returns {} until memory is wired
        memory_data: dict[str, Any] = {}
        if self.memory_retriever:
            memory_data["memories"] = await self.memory_retriever(
                request.input_text, decision.memory_strategy
            )

        # L5: Prompt assembly
        prompt = await self.prompt_os.assemble(request, memory_data, decision.agent_id)

        # L6-L7: Execution
        agent = self.agents.get(decision.agent_id, self.agents.get("BUDDY"))
        if not agent:
            raise RuntimeError(f"No agent registered for {decision.agent_id}")

        full_response = ""
        async for chunk in agent.execute(prompt):
            full_response += chunk

        # Finalize
        state.history.append({"user": request.input_text, "assistant": full_response})
        state.turn_count += 1
        await self.bus.emit(
            "turn_end",
            {"session_id": request.session_id, "status": "complete", "agent": decision.agent_id},
        )
        return full_response
