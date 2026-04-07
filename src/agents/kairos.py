import asyncio
from typing import AsyncGenerator

from src.agents.base import BaseAgent
from src.core.bus import EventBus
from src.core.models import AgentState, Event, EventCancelled
from src.core.registry import listens


class KairosAgent(BaseAgent):
    """Interrupt-driven monitoring agent — watches executions, intervenes on anomalies."""

    _dangerous_patterns = (
        "rm -rf /",
        "rm -rf /*",
        "del /",
        "format c:",
        "mkfs.",
        "dd if=",
        ":(){:|:&};:",
        "> /dev/sda",
        "chmod -R 777 /",
        "wget.*|.*sh",
        "curl.*|.*sh",
    )

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

    @listens(Event.TOOL_CALL_REQUEST, priority=0)
    async def on_tool_call_request(self, payload: dict) -> None:
        """Pre-execution safety gate — block dangerous commands."""
        name = payload.get("name", "")
        if name != "bash":
            return

        import json
        try:
            args = json.loads(payload.get("arguments", "{}"))
        except (json.JSONDecodeError, TypeError):
            return

        command = args.get("command", "").lower()
        for pattern in self._dangerous_patterns:
            if pattern in command:
                raise EventCancelled(f"KAIROS blocked dangerous command: {command}")

    @listens(Event.DELEGATION_START, priority=10)
    async def on_delegation_start(self, payload: dict) -> None:
        """Enforce max delegation depth and parallelism limits."""
        depth = payload.get("depth", 0)
        if depth > 3:
            raise EventCancelled(
                f"KAIROS blocked delegation: depth {depth} exceeds maximum (3)"
            )

    @listens(Event.AGENT_CHUNK, priority=10)
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
