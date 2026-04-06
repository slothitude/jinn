from __future__ import annotations

import asyncio
from typing import AsyncGenerator, TYPE_CHECKING

from src.agents.base import BaseAgent
from src.core.bus import EventBus
from src.core.models import Event, AgentState, ToolCall

if TYPE_CHECKING:
    from src.execution.toolbox import ToolExecutor


class BuddyAgent(BaseAgent):
    """Collaborative engineering assistant — default agent for code tasks."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__("BUDDY", bus)
        self._interrupted = False
        self._tool_executor: ToolExecutor | None = None
        self.bus.subscribe(Event.KAIROS_INTERRUPT, self._handle_interrupt)

    def set_tool_executor(self, executor: ToolExecutor) -> None:
        """Wire in a ToolExecutor for the agentic tool loop."""
        self._tool_executor = executor

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

                step_prompt = f"PLAN CONTEXT: {prompt}\nCURRENT STEP: {node.action}"

                try:
                    async for token in self._run_tool_loop(step_prompt):
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
                        break

                except Exception as e:
                    node.status = "failed"
                    yield f"\n[ERROR] Step failed: {e}"
                    break

            if not self._interrupted and state.current_node_index >= len(state.execution_graph.nodes):
                yield "\n\n--- PLAN COMPLETE ---"
                state.execution_graph = None

        # Scenario B: Single-shot prompt
        else:
            try:
                async for token in self._run_tool_loop(prompt):
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

    async def _run_tool_loop(
        self, initial_prompt: str, max_iterations: int = 10
    ) -> AsyncGenerator[str, None]:
        """Agentic tool loop — streams LLM content, executes tool calls, loops.

        If no ToolExecutor is wired, falls back to plain stream_llm().
        """
        if self._tool_executor is None:
            async for token in self.stream_llm(initial_prompt):
                yield token
            return

        from src.execution.toolbox import DEFAULT_TOOLS

        tools = [t.to_openai_format() for t in DEFAULT_TOOLS]
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

            # Build assistant message with tool calls for conversation history
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

            # Execute each tool call and append results
            for tc in tool_calls_collected:
                result = await self._tool_executor.execute(tc)
                messages.append({
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.output,
                })

    async def steer(self, message: str) -> None:
        self._interrupted = True
        await self.bus.emit(Event.KAIROS_INTERRUPT, {"target": self.name, "message": message})
