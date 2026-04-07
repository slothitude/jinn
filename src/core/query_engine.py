import json
import re
from typing import Any, Callable, Coroutine, Dict, Optional, Set

from src.core.bus import EventBus
from src.core.models import AgentRequest, AgentState, Event, PlanGraph
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
        self.wiki_retriever: Optional[Callable[..., Coroutine]] = None

    def register_agent(self, agent: BaseAgent) -> None:
        self.agents[agent.name] = agent

    def _parse_plan(self, text: str) -> Optional[PlanGraph]:
        """Extract JSON PlanGraph from agent output."""
        try:
            # Look for JSON block
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                # Validate it's a PlanGraph (basic check)
                if "nodes" in data:
                    plan = PlanGraph(**data)
                    # Strip unknown tool names so nodes degrade to slow path
                    known: Set[str] = {t.name for t in self._known_tools()}
                    for node in plan.nodes:
                        if node.tool and node.tool not in known:
                            node.tool = None
                            node.tool_args = None
                    return plan
        except Exception:
            pass
        return None

    @staticmethod
    def _known_tools():
        from src.execution.toolbox import DEFAULT_TOOLS
        return DEFAULT_TOOLS

    async def process(self, request: AgentRequest, state: AgentState) -> str:
        await self.bus.emit(Event.TURN_START, {"session_id": request.session_id})

        # L3: Policy decision
        decision = await self.policy.decide(request)

        # L4: Memory retrieval — use wiki-aware retrieval when available
        memory_data: dict[str, Any] = {}
        if self.wiki_retriever:
            memory_data = await self.wiki_retriever(
                request.input_text, decision.memory_strategy
            )
        elif self.memory_retriever:
            memory_data["memories"] = await self.memory_retriever(
                request.input_text, decision.memory_strategy
            )

        # L5: Prompt assembly
        prompt = await self.prompt_os.assemble(request, memory_data, decision.agent_id)

        # L6-L7: Execution
        agent = self.agents.get(decision.agent_id, self.agents.get("BUDDY"))
        if not agent:
            raise RuntimeError(f"No agent registered for {decision.agent_id}")

        # Ensure KAIROS knows about the current state if it's not the main agent
        kairos = self.agents.get("KAIROS")
        if kairos and agent != kairos:
            # We don't need the output, just to trigger it setting its state
            # and potentially doing its own background monitoring if it had some.
            # For now, we just ensure it has the state.
            if hasattr(kairos, 'current_state'):
                kairos.current_state = state

        full_response = ""
        async for chunk in agent.execute(prompt, state):
            full_response += chunk

        # If ULTRAPLAN generated a plan, store it and then execute via BUDDY
        if decision.agent_id == "ULTRAPLAN":
            plan = self._parse_plan(full_response)
            if plan:
                state.execution_graph = plan
                state.current_node_index = 0
                await self.bus.emit(Event.AGENT_CHUNK, {"agent": "SYSTEM", "chunk": "\n[PLAN DETECTED] Swapping to BUDDY for execution...\n"})
                
                # Delegate to BUDDY for multi-step execution
                buddy = self.agents.get("BUDDY")
                if buddy:
                    # Pass plan context so BUDDY renders in PLAN EXECUTION MODE
                    handoff_request = AgentRequest(
                        session_id=request.session_id,
                        input_text=full_response,
                        metadata={"is_plan_execution": True},
                    )
                    handoff_prompt = await self.prompt_os.assemble(handoff_request, memory_data, "BUDDY")
                    async for chunk in buddy.execute(handoff_prompt, state):
                        full_response += chunk

        # Finalize
        state.history.append({"user": request.input_text, "assistant": full_response})
        state.turn_count += 1
        await self.bus.emit(
            Event.TURN_END,
            {"session_id": request.session_id, "status": "complete", "agent": decision.agent_id},
        )
        return full_response
