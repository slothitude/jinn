"""SupervisorAgent — Tier 1: Scoped task planning with parallel worker spawning."""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, TYPE_CHECKING

from src.agents.base import BaseAgent
from src.core.bus import EventBus
from src.core.models import AgentState, Event, ToolCall
from src.core.registry import listens
from src.execution.agent_tools import SPAWN_WORKERS_TOOL
from src.execution.toolbox import BASH_TOOL, READ_TOOL

if TYPE_CHECKING:
    from src.execution.agent_tools import AgentToolExecutor


class SupervisorAgent(BaseAgent):
    """Middle-tier agent. Receives scoped tasks, spawns parallel workers."""

    def __init__(self, bus: EventBus, provider: str | None = None) -> None:
        super().__init__("SUPERVISOR", bus, provider=provider)
        self._interrupted = False

    @listens(Event.KAIROS_INTERRUPT, priority=50)
    async def _handle_interrupt(self, payload: dict) -> None:
        target = payload.get("target")
        if target == self.name or target == "ALL":
            await self.steer(payload.get("message", "Interrupted by KAIROS"))

    async def execute(
        self, prompt: str, state: AgentState | None = None
    ) -> AsyncGenerator[str, None]:
        self._interrupted = False
        await self.bus.emit(Event.AGENT_START, {"agent": self.name})

        try:
            async for token in self._run_tool_loop(prompt):
                if self._interrupted:
                    yield "\n[INTERRUPTED]"
                    break
                yield token
                await self.bus.emit(
                    Event.AGENT_CHUNK, {"agent": self.name, "chunk": token}
                )
        except Exception:
            response = f"[{self.name}] Supervising: {prompt}"
            for chunk in response.split(" "):
                if self._interrupted:
                    yield "\n[INTERRUPTED]"
                    break
                await asyncio.sleep(0.02)
                token = chunk + " "
                yield token
                await self.bus.emit(
                    Event.AGENT_CHUNK, {"agent": self.name, "chunk": token}
                )

        await self.bus.emit(Event.AGENT_END, {"agent": self.name})

    async def _run_tool_loop(
        self, initial_prompt: str, max_iterations: int = 8
    ) -> AsyncGenerator[str, None]:
        """Tool loop using spawn_workers, bash, and read tools."""
        if self._agent_tool_executor is None:
            async for token in self.stream_llm(initial_prompt):
                yield token
            return

        tools = [
            SPAWN_WORKERS_TOOL.to_openai_format(),
            BASH_TOOL.to_openai_format(),
            READ_TOOL.to_openai_format(),
        ]
        messages: list[dict] = [{"role": "user", "content": initial_prompt}]

        for _ in range(max_iterations):
            content_parts: list[str] = []
            tool_calls_collected: list[ToolCall] = []

            async for event in self.stream_llm_with_tools(messages, tools=tools):
                if event.type == "content":
                    content_parts.append(event.content)
                    yield event.content
                elif event.type == "tool_call":
                    tool_calls_collected.append(
                        ToolCall(
                            id=event.tool_call_id,
                            name=event.tool_call_name,
                            arguments=event.tool_call_arguments,
                        )
                    )

            if not tool_calls_collected:
                break

            messages.append({
                "role": "assistant",
                "content": "".join(content_parts) or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in tool_calls_collected
                ],
            })

            for tc in tool_calls_collected:
                result = await self._agent_tool_executor.execute(tc)
                messages.append({
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.output,
                })

    async def steer(self, message: str) -> None:
        self._interrupted = True
