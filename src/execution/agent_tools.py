"""Agent-to-agent delegation bridge with parallel batch execution."""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4
from typing import TYPE_CHECKING

from src.core.bus import EventBus
from src.core.models import (
    AgentState,
    DelegationContext,
    DelegationResult,
    Event,
    ToolCall,
    ToolResult,
)
from src.execution.toolbox import ToolSchema

if TYPE_CHECKING:
    from src.agents.base import BaseAgent
    from src.execution.toolbox import ToolExecutor


# --- Delegation tool schemas ---

DELEGATE_BATCH_TOOL = ToolSchema(
    name="delegate_batch",
    description="Delegate multiple subtasks in parallel to Supervisor agents.",
    parameters={
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "constraints": {"type": "string"},
                        "supervisor_type": {
                            "type": "string",
                            "enum": ["code", "research", "testing", "general"],
                        },
                        "provider": {
                            "type": "string",
                            "description": "Optional provider override (e.g. 'nvidia', 'zhipu')",
                        },
                        "model": {
                            "type": "string",
                            "description": "Optional model override for the worker",
                        },
                    },
                    "required": ["task"],
                },
                "description": "Array of subtask definitions to delegate in parallel",
            },
        },
        "required": ["tasks"],
    },
    cost_factor=3.0,
)

SPAWN_WORKERS_TOOL = ToolSchema(
    name="spawn_workers",
    description="Spawn multiple Worker agents in parallel.",
    parameters={
        "type": "object",
        "properties": {
            "workers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "acceptance_criteria": {"type": "string"},
                        "provider": {
                            "type": "string",
                            "description": "Optional provider override (e.g. 'nvidia', 'zhipu')",
                        },
                        "model": {
                            "type": "string",
                            "description": "Optional model override for the worker",
                        },
                    },
                    "required": ["task"],
                },
            },
        },
        "required": ["workers"],
    },
    cost_factor=2.0,
)


class AgentToolExecutor:
    """Intercepts agent-call tool calls, runs target agents with fresh state.

    Falls through to ToolExecutor for standard tools (bash/read/write).
    """

    def __init__(
        self,
        bus: EventBus,
        agents: dict[str, BaseAgent],
        tool_executor: ToolExecutor,
    ) -> None:
        self.bus = bus
        self.agents = agents
        self.tool_executor = tool_executor
        self._delegation_depth = 0
        self._max_depth = 3

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Route tool call: delegation tools -> agents, others -> ToolExecutor."""
        if tool_call.name in ("delegate_batch", "spawn_workers"):
            return await self._execute_delegation(tool_call)
        return await self.tool_executor.execute(tool_call)

    async def _execute_delegation(self, tool_call: ToolCall) -> ToolResult:
        """Handle delegate_batch and spawn_workers with parallel gather."""
        self._delegation_depth += 1
        if self._delegation_depth > self._max_depth:
            self._delegation_depth -= 1
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=f"Delegation depth limit ({self._max_depth}) reached. Stop delegating.",
                success=False,
            )

        try:
            args = json.loads(tool_call.arguments)
        except json.JSONDecodeError as e:
            self._delegation_depth -= 1
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=f"Invalid JSON arguments: {e}",
                success=False,
            )

        if tool_call.name == "delegate_batch":
            task_specs = args.get("tasks", [])
            target_agent_name = "SUPERVISOR"
        else:  # spawn_workers
            task_specs = args.get("workers", [])
            target_agent_name = "BUDDY"

        if not task_specs:
            self._delegation_depth -= 1
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output="No tasks provided. Provide at least one task.",
                success=False,
            )

        agent = self.agents.get(target_agent_name)
        if agent is None:
            self._delegation_depth -= 1
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=f"Agent '{target_agent_name}' not registered.",
                success=False,
            )

        async def run_task(idx: int, spec: dict) -> tuple[int, str, bool]:
            task_desc = spec.get("task", "")
            constraints = spec.get("constraints", "") or spec.get("acceptance_criteria", "")
            task_provider = spec.get("provider")
            task_model = spec.get("model")

            ctx = DelegationContext(
                task_description=task_desc,
                constraints=constraints,
            )
            scoped_state = AgentState(session_id=f"del-{uuid4().hex[:8]}", history=[])

            # Pick agent — optionally create a fresh one with per-task provider
            task_agent = agent
            if task_provider and task_provider != agent._provider:
                # Create a fresh agent for this specific provider
                task_agent = type(agent)(
                    name=agent.name, bus=agent.bus, provider=task_provider
                )
                if task_agent._agent_tool_executor is None and agent._agent_tool_executor:
                    task_agent._agent_tool_executor = agent._agent_tool_executor
            if task_model:
                task_agent._model = task_model

            await self.bus.emit(Event.DELEGATION_START, {
                "task": task_desc,
                "tier": target_agent_name,
                "index": idx,
                "session_id": scoped_state.session_id,
            })
            prompt = task_desc
            if constraints:
                prompt += f"\n\nConstraints: {constraints}"

            result_text = ""
            try:
                async for chunk in task_agent.execute(prompt, scoped_state):
                    result_text += chunk
                success = True
            except Exception as e:
                result_text = f"Error: {e}"
                success = False

            await self.bus.emit(Event.DELEGATION_END, {
                "task": task_desc,
                "tier": target_agent_name,
                "index": idx,
                "success": success,
                "session_id": scoped_state.session_id,
            })
            return idx, result_text, success

        # PARALLEL: all agents run concurrently via asyncio.gather
        outcomes = await asyncio.gather(
            *[run_task(i, t) for i, t in enumerate(task_specs)],
            return_exceptions=True,
        )

        parts: list[str] = []
        all_success = True
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                parts.append(f"[Error]: {outcome}")
                all_success = False
            else:
                idx, text, ok = outcome
                label = f"Agent-{idx}"
                parts.append(f"[{label}]: {text}")
                if not ok:
                    all_success = False

        combined = "\n---\n".join(parts)
        self._delegation_depth -= 1

        return ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            output=combined,
            success=all_success,
        )
