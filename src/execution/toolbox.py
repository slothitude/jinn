from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from src.core.bus import EventBus
from src.core.models import Event, EventCancelled, ToolCall, ToolResult


class ToolSchema(BaseModel):
    """Schema definition for a tool that agents can invoke."""

    name: str
    description: str
    parameters: Dict[str, Any]
    cost_factor: float = 1.0

    def to_openai_format(self) -> Dict[str, Any]:
        """Return dict for OpenAI function-calling `tools` param."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def render(self) -> str:
        """Render as text for Jinja2 template injection."""
        params = json.dumps(self.parameters, indent=2)
        return f"**{self.name}** (cost: {self.cost_factor})\n{self.description}\nParameters:\n{params}"


# --- Pre-built tool schemas ---

BASH_TOOL = ToolSchema(
    name="bash",
    description="Run a bash command and return stdout/stderr.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "number", "description": "Timeout in seconds (default 30)"},
        },
        "required": ["command"],
    },
    cost_factor=1.5,
)

READ_TOOL = ToolSchema(
    name="read",
    description="Read the contents of a file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path"},
        },
        "required": ["path"],
    },
    cost_factor=0.5,
)

WRITE_TOOL = ToolSchema(
    name="write",
    description="Write content to a file within the sandbox directory.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path (relative to sandbox)"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    },
    cost_factor=1.0,
)

DEFAULT_TOOLS: List[ToolSchema] = [BASH_TOOL, READ_TOOL, WRITE_TOOL]


class ToolExecutor:
    """Executes tool calls with safety checks via EventBus."""

    def __init__(
        self,
        bus: EventBus,
        sandbox_dir: Optional[str] = None,
        default_timeout: float = 30.0,
    ) -> None:
        self.bus = bus
        self.sandbox_dir = sandbox_dir or os.path.join(os.getcwd(), "sandbox")
        self.default_timeout = default_timeout

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call with KAIROS safety gate."""
        # Emit request — KAIROS can raise EventCancelled to block
        result = await self.bus.emit(
            Event.TOOL_CALL_REQUEST,
            {"id": tool_call.id, "name": tool_call.name, "arguments": tool_call.arguments},
        )
        if result.cancelled:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output="Tool call blocked by safety gate",
                success=False,
            )

        # Parse arguments
        try:
            args = json.loads(tool_call.arguments)
        except json.JSONDecodeError as e:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=f"Invalid JSON arguments: {e}",
                success=False,
            )

        # Dispatch
        dispatchers = {
            "bash": self._execute_bash,
            "read": self._execute_read,
            "write": self._execute_write,
        }
        handler = dispatchers.get(tool_call.name)
        if handler is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                output=f"Unknown tool: {tool_call.name}",
                success=False,
            )

        output, success = await handler(args)
        tool_result = ToolResult(
            tool_call_id=tool_call.id,
            name=tool_call.name,
            output=output,
            success=success,
        )

        await self.bus.emit(
            Event.TOOL_CALL_RESULT,
            {"tool_call_id": tool_result.tool_call_id, "name": tool_result.name, "success": success},
        )
        return tool_result

    async def _execute_bash(self, args: Dict[str, Any]) -> tuple[str, bool]:
        """Run a bash command with timeout."""
        command = args.get("command", "")
        timeout = args.get("timeout", self.default_timeout)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.sandbox_dir if os.path.isdir(self.sandbox_dir) else None,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace")
            if stderr:
                output += "\n" + stderr.decode(errors="replace")
            return output, proc.returncode == 0
        except asyncio.TimeoutError:
            proc.kill()
            return f"Command timed out after {timeout}s", False
        except Exception as e:
            return str(e), False

    async def _execute_read(self, args: Dict[str, Any]) -> tuple[str, bool]:
        """Read file contents."""
        path = args.get("path", "")
        try:
            content = Path(path).read_text(encoding="utf-8")
            return content, True
        except FileNotFoundError:
            return f"File not found: {path}", False
        except Exception as e:
            return str(e), False

    async def _execute_write(self, args: Dict[str, Any]) -> tuple[str, bool]:
        """Write file contents, sandboxed to sandbox_dir."""
        path = args.get("path", "")
        content = args.get("content", "")

        # Resolve and prevent path traversal
        sandbox = Path(self.sandbox_dir).resolve()
        target = (sandbox / path).resolve()
        if not str(target).startswith(str(sandbox)):
            return f"Path traversal blocked: {path}", False

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} chars to {path}", True
        except Exception as e:
            return str(e), False
