from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, TYPE_CHECKING

from src.agents.base import BaseAgent
from src.core.bus import EventBus
from src.core.models import Event, AgentState, ToolCall
from src.core.registry import listens

if TYPE_CHECKING:
    from src.execution.toolbox import ToolExecutor


class BuddyAgent(BaseAgent):
    """Collaborative engineering assistant — default agent for code tasks."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__("BUDDY", bus)
        self._interrupted = False
        self._tool_executor: ToolExecutor | None = None

    def set_tool_executor(self, executor: ToolExecutor) -> None:
        """Wire in a ToolExecutor for the agentic tool loop."""
        self._tool_executor = executor

    @listens(Event.KAIROS_INTERRUPT, priority=50)
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
                    # Fast path: node has a pre-specified tool
                    if node.tool and self._tool_executor:
                        tc = ToolCall(
                            id=f"plan-{node.id}",
                            name=node.tool,
                            arguments=json.dumps(node.tool_args or {}),
                        )
                        result = await self._tool_executor.execute(tc)
                        if result.success:
                            yield result.output
                            await self.bus.emit(Event.AGENT_CHUNK, {"agent": self.name, "chunk": result.output})
                            node.status = "completed"
                            state.current_node_index += 1
                            continue
                        else:
                            # Fast path failed — fall through to LLM for recovery
                            yield f"\n[FAST PATH FAILED] {result.output}\n"
                            step_prompt += f"\nPrevious tool call ({node.tool}) failed: {result.output}\n"

                    async for token in self._run_tool_loop(step_prompt, state=state):
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
                async for token in self._run_tool_loop(prompt, state=state):
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
        self, initial_prompt: str, max_iterations: int = 10,
        state: AgentState | None = None,
    ) -> AsyncGenerator[str, None]:
        """Agentic tool loop — streams LLM content, executes tool calls, loops.

        If no ToolExecutor is wired, falls back to plain stream_llm().
        """
        user_input = state.current_input if state and state.current_input else initial_prompt

        # Build conversation history from state
        history_msgs: list[dict] = []
        if state and state.history:
            for turn in state.history[-10:]:  # last 10 turns for context window
                if "user" in turn:
                    history_msgs.append({"role": "user", "content": turn["user"]})
                if "assistant" in turn:
                    history_msgs.append({"role": "assistant", "content": turn["assistant"]})

        if self._tool_executor is None:
            # Build full message list for the no-tools path
            no_tool_messages = [
                {"role": "system", "content": initial_prompt},
                *history_msgs,
                {"role": "user", "content": user_input},
            ]
            from src.core.provider import stream_chat
            async for token in stream_chat(
                client=self._client, model=self._model, messages=no_tool_messages,
            ):
                yield token
            return

        from src.execution.toolbox import DEFAULT_TOOLS
        from src.execution.web_tools import WEB_TOOLS

        tools = [t.to_openai_format() for t in DEFAULT_TOOLS + WEB_TOOLS]
        messages: list[dict] = [
            {"role": "system", "content": initial_prompt},
            *history_msgs,
            {"role": "user", "content": user_input},
        ]

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
