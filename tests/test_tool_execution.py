import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from src.core.bus import EventBus
from src.core.models import Event, EventCancelled, ToolCall, ToolResult
from src.execution.toolbox import BASH_TOOL, READ_TOOL, WRITE_TOOL, ToolExecutor, ToolSchema


# --- ToolSchema render + format ---


def test_tool_schema_render():
    schema = ToolSchema(
        name="test_tool",
        description="A test tool.",
        parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
        cost_factor=2.0,
    )
    rendered = schema.render()
    assert "test_tool" in rendered
    assert "2.0" in rendered
    assert "A test tool." in rendered

    fmt = schema.to_openai_format()
    assert fmt["type"] == "function"
    assert fmt["function"]["name"] == "test_tool"
    assert fmt["function"]["parameters"]["properties"]["x"]["type"] == "integer"


# --- ToolExecutor: bash ---


@pytest.mark.asyncio
async def test_tool_executor_bash():
    bus = EventBus()
    executor = ToolExecutor(bus)

    tool_call = ToolCall(id="tc1", name="bash", arguments='{"command": "echo hello"}')
    result = await executor.execute(tool_call)
    assert result.success is True
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_tool_executor_bash_timeout():
    bus = EventBus()
    executor = ToolExecutor(bus, default_timeout=0.5)

    tool_call = ToolCall(
        id="tc2", name="bash", arguments='{"command": "sleep 10", "timeout": 0.5}'
    )
    result = await executor.execute(tool_call)
    assert result.success is False
    assert "timed out" in result.output.lower()


# --- ToolExecutor: read ---


@pytest.mark.asyncio
async def test_tool_executor_read_file():
    bus = EventBus()
    executor = ToolExecutor(bus)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("test content here")
        f.flush()
        path = f.name

    tool_call = ToolCall(id="tc3", name="read", arguments=json.dumps({"path": path.replace("\\", "/")}))
    result = await executor.execute(tool_call)
    assert result.success is True
    assert "test content here" in result.output

    Path(path).unlink()


# --- ToolExecutor: write (sandbox + path traversal) ---


@pytest.mark.asyncio
async def test_tool_executor_write_sandbox():
    bus = EventBus()

    with tempfile.TemporaryDirectory() as sandbox:
        executor = ToolExecutor(bus, sandbox_dir=sandbox)

        # Successful write inside sandbox
        tool_call = ToolCall(
            id="tc4",
            name="write",
            arguments='{"path": "subdir/test.txt", "content": "hello world"}',
        )
        result = await executor.execute(tool_call)
        assert result.success is True

        written = (Path(sandbox) / "subdir" / "test.txt").read_text()
        assert written == "hello world"

        # Path traversal blocked
        tool_call_bad = ToolCall(
            id="tc5",
            name="write",
            arguments='{"path": "../escape.txt", "content": "nope"}',
        )
        result_bad = await executor.execute(tool_call_bad)
        assert result_bad.success is False
        assert "blocked" in result_bad.output.lower()


# --- KAIROS safety gate ---


@pytest.mark.asyncio
async def test_kairos_blocks_dangerous_command():
    from src.agents.kairos import KairosAgent

    bus = EventBus()
    kairos = KairosAgent(bus)
    executor = ToolExecutor(bus)

    tool_call = ToolCall(
        id="tc6", name="bash", arguments='{"command": "rm -rf /"}'
    )
    result = await executor.execute(tool_call)
    assert result.success is False
    assert "blocked" in result.output.lower()


@pytest.mark.asyncio
async def test_kairos_allows_safe_command():
    from src.agents.kairos import KairosAgent

    bus = EventBus()
    kairos = KairosAgent(bus)
    executor = ToolExecutor(bus)

    tool_call = ToolCall(
        id="tc7", name="bash", arguments='{"command": "echo hello"}'
    )
    result = await executor.execute(tool_call)
    assert result.success is True
    assert "hello" in result.output


# --- PromptOS tools_list injection ---


@pytest.mark.asyncio
async def test_promptos_injects_tools_list():
    from src.core.models import AgentRequest
    from src.promptos.engine import PromptOS

    promptos = PromptOS()
    request = AgentRequest(session_id="test", input_text="hello")
    output = await promptos.assemble(request, {"memories": []}, "BUDDY")
    assert "bash" in output.lower()
    assert "read" in output.lower()
    assert "write" in output.lower()
