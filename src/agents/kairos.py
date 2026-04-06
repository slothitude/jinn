import asyncio
from typing import AsyncGenerator

from src.agents.base import BaseAgent
from src.core.bus import EventBus
from src.core.models import AgentState, Event


class KairosAgent(BaseAgent):
    """Interrupt-driven monitoring agent — watches executions, intervenes on anomalies."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__("KAIROS", bus)
        self._anomaly_keywords = {"error", "timeout", "forbidden", "unsafe", "exception"}
        self.current_state: AgentState | None = None

    async def execute(self, prompt: str, state: AgentState | None = None) -> AsyncGenerator[str, None]:
        self.current_state = state
        await self.bus.emit(Event.AGENT_START, {"agent": self.name})

        response = f"[{self.name}] Monitoring active. No anomalies detected."
        for chunk in response.split(" "):
            await asyncio.sleep(0.02)
            token = chunk + " "
            yield token
            await self.bus.emit(Event.AGENT_CHUNK, {"agent": self.name, "chunk": token})

        await self.bus.emit(Event.AGENT_END, {"agent": self.name})

    def detect_anomaly(self, payload: dict) -> bool:
        chunk = payload.get("chunk", "").lower()
        
        # Text-level anomaly detection
        if any(kw in chunk for kw in self._anomaly_keywords):
            return True
            
        # Plan-level anomaly detection (e.g., if current node index exceeds graph size)
        if self.current_state and self.current_state.execution_graph:
            if self.current_state.current_node_index >= len(self.current_state.execution_graph.nodes):
                return True # Out of bounds
                
        return False

    async def on_agent_chunk(self, payload: dict) -> None:
        """EventBus subscriber — monitors other agents' output for anomalies."""
        if payload.get("agent") == self.name:
            return # Don't monitor ourselves

        if self.detect_anomaly(payload):
            # Plan-level steering message
            message = "Anomaly detected in execution chunk"
            if self.current_state and self.current_state.execution_graph:
                node_idx = self.current_state.current_node_index
                message = f"Plan risk at step {node_idx}: detected potential failure pattern."

            await self.bus.emit(
                Event.KAIROS_INTERRUPT,
                {
                    "source": self.name, 
                    "target": payload.get("agent", "ALL"),
                    "anomaly": payload["chunk"],
                    "message": message
                },
            )
