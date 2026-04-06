import asyncio
from typing import AsyncGenerator

from src.agents.base import BaseAgent
from src.core.bus import EventBus
from src.core.models import Event, AgentState


class BuddyAgent(BaseAgent):
    """Collaborative engineering assistant — default agent for code tasks."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__("BUDDY", bus)
        self._interrupted = False
        self.bus.subscribe(Event.KAIROS_INTERRUPT, self._handle_interrupt)

    async def _handle_interrupt(self, payload: dict) -> None:
        """Handle global interrupt signal."""
        target = payload.get("target")
        if target == self.name or target == "ALL":
            message = payload.get("message", "Interrupted by KAIROS")
            await self.steer(message)

    async def execute(self, prompt: str, state: AgentState | None = None) -> AsyncGenerator[str, None]:
        self._interrupted = False
        await self.bus.emit(Event.AGENT_START, {"agent": self.name})

        # Scenario A: Follow a PlanGraph
        if state and state.execution_graph:
            yield f"### [BUDDY] Executing Plan: {state.session_id}\n"
            
            while state.current_node_index < len(state.execution_graph.nodes):
                node = state.execution_graph.nodes[state.current_node_index]
                node.status = "in_progress"
                
                yield f"\n--- Step {node.id}: {node.action} ---\n"
                
                # Assemble step prompt
                step_prompt = f"PLAN CONTEXT: {prompt}\nCURRENT STEP: {node.action}"
                
                try:
                    async for token in self.stream_llm(step_prompt):
                        if self._interrupted:
                            node.status = "failed"
                            yield "\n[INTERRUPTED]"
                            break
                        yield token
                        await self.bus.emit(Event.AGENT_CHUNK, {"agent": self.name, "chunk": token})
                    
                    if not self._interrupted:
                        node.status = "completed"
                        state.current_node_index += 1
                    else:
                        break # Break while loop if interrupted
                        
                except Exception as e:
                    node.status = "failed"
                    yield f"\n[ERROR] Step failed: {e}"
                    break
                    
            if not self._interrupted and state.current_node_index >= len(state.execution_graph.nodes):
                yield "\n\n--- PLAN COMPLETE ---"
                state.execution_graph = None # Clear plan when done
        
        # Scenario B: Single-shot prompt
        else:
            try:
                async for token in self.stream_llm(prompt):
                    if self._interrupted:
                        yield "\n[INTERRUPTED]"
                        break
                    yield token
                    await self.bus.emit(Event.AGENT_CHUNK, {"agent": self.name, "chunk": token})
            except Exception:
                # Fallback to echo-based simulation if LLM is unavailable
                response = f"[{self.name}] Processing: {prompt}"
                for chunk in response.split(" "):
                    if self._interrupted:
                        yield "\n[INTERRUPTED]"
                        break
                    await asyncio.sleep(0.02)
                    token = chunk + " "
                    yield token
                    await self.bus.emit(Event.AGENT_CHUNK, {"agent": self.name, "chunk": token})

        await self.bus.emit(Event.AGENT_END, {"agent": self.name})

    async def steer(self, message: str) -> None:
        self._interrupted = True
        await self.bus.emit(Event.KAIROS_INTERRUPT, {"target": self.name, "message": message})
