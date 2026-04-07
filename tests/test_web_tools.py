"""Tests for web tools schemas, adapter, and dispatch integration."""

import asyncio
import json

import pytest

from src.core.bus import EventBus
from src.core.models import ToolCall, ToolResult
from src.execution.toolbox import ToolExecutor
from src.execution.agent_tools import AgentToolExecutor
from src.execution.web_tools import (
    WEB_TOOLS,
    WEB_SEARCH_TOOL,
    WEB_CRAWL_TOOL,
    WEB_SUMMARIZE_TOOL,
    WEB_ASK_TOOL,
    WEB_SEE_TOOL,
    WEB_LOOK_TOOL,
    WebToolsAdapter,
)


# ---------------------------------------------------------------------------
# Tool schema tests
# ---------------------------------------------------------------------------


class TestToolSchemas:
    """All 6 web tool schemas produce valid OpenAI function-calling format."""

    @pytest.mark.parametrize("tool", WEB_TOOLS, ids=lambda t: t.name)
    def test_to_openai_format(self, tool):
        fmt = tool.to_openai_format()
        assert fmt["type"] == "function"
        fn = fmt["function"]
        assert fn["name"] == tool.name
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert "required" in fn["parameters"]

    def test_six_tools_defined(self):
        assert len(WEB_TOOLS) == 6

    def test_search_schema(self):
        fmt = WEB_SEARCH_TOOL.to_openai_format()
        props = fmt["function"]["parameters"]["properties"]
        assert "query" in props
        assert "limit" in props
        assert fmt["function"]["parameters"]["required"] == ["query"]

    def test_crawl_schema(self):
        fmt = WEB_CRAWL_TOOL.to_openai_format()
        props = fmt["function"]["parameters"]["properties"]
        assert "urls" in props
        assert props["urls"]["type"] == "array"

    def test_summarize_schema(self):
        fmt = WEB_SUMMARIZE_TOOL.to_openai_format()
        props = fmt["function"]["parameters"]["properties"]
        assert "urls" in props
        assert "instruction" in props

    def test_ask_schema(self):
        fmt = WEB_ASK_TOOL.to_openai_format()
        props = fmt["function"]["parameters"]["properties"]
        assert "question" in props
        assert "scrape_top" in props

    def test_see_schema(self):
        fmt = WEB_SEE_TOOL.to_openai_format()
        props = fmt["function"]["parameters"]["properties"]
        assert "urls" in props
        assert "instruction" in props
        assert "extract_prompt" in props

    def test_look_schema(self):
        fmt = WEB_LOOK_TOOL.to_openai_format()
        props = fmt["function"]["parameters"]["properties"]
        assert "image_base64" in props
        assert "instruction" in props


# ---------------------------------------------------------------------------
# WebToolsAdapter graceful degradation
# ---------------------------------------------------------------------------


class TestWebToolsAdapter:
    """Adapter returns clear errors when web_eyes is not installed."""

    @pytest.fixture
    def adapter(self):
        return WebToolsAdapter()

    def test_is_available_returns_bool(self):
        result = WebToolsAdapter.is_available()
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_search_unavailable(self, adapter):
        result = await adapter.search("test query")
        assert "unavailable" in result.lower() or "error" in result.lower()
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_crawl_unavailable(self, adapter):
        result = await adapter.crawl(["https://example.com"])
        assert "unavailable" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_summarize_unavailable(self, adapter):
        result = await adapter.summarize(["https://example.com"])
        assert "unavailable" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_ask_unavailable(self, adapter):
        result = await adapter.ask("What is Python?")
        assert "unavailable" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_see_unavailable(self, adapter):
        result = await adapter.see(["https://example.com"])
        assert "unavailable" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_look_unavailable(self, adapter):
        result = await adapter.look("dGVzdA==")
        assert "unavailable" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_close_noop(self, adapter):
        # close() should not raise even if crawler was never created
        await adapter.close()


# ---------------------------------------------------------------------------
# ToolExecutor dispatch tests
# ---------------------------------------------------------------------------


class TestToolExecutorWebDispatch:
    """ToolExecutor correctly routes all 6 web tool names."""

    @pytest.fixture
    def executor(self):
        bus = EventBus()
        return ToolExecutor(bus)

    @pytest.mark.parametrize("tool_name", [
        "web_search", "web_crawl", "web_summarize",
        "web_ask", "web_see", "web_look",
    ])
    @pytest.mark.asyncio
    async def test_web_tool_dispatched(self, executor, tool_name):
        """Each web tool is recognized and returns a result (error if no web_eyes)."""
        args = {}
        if tool_name == "web_search":
            args = {"query": "test"}
        elif tool_name == "web_crawl":
            args = {"urls": ["https://example.com"]}
        elif tool_name == "web_summarize":
            args = {"urls": ["https://example.com"]}
        elif tool_name == "web_ask":
            args = {"question": "test"}
        elif tool_name == "web_see":
            args = {"urls": ["https://example.com"]}
        elif tool_name == "web_look":
            args = {"image_base64": "dGVzdA=="}

        tc = ToolCall(id="test-1", name=tool_name, arguments=json.dumps(args))
        result = await executor.execute(tc)
        assert isinstance(result, ToolResult)
        assert result.tool_call_id == "test-1"
        # Without web_eyes installed, result should mention unavailable or error
        lower = result.output.lower()
        assert "unavailable" in lower or "error" in lower

    @pytest.mark.asyncio
    async def test_unknown_tool_still_fails(self, executor):
        tc = ToolCall(id="test-x", name="nonexistent_tool", arguments="{}")
        result = await executor.execute(tc)
        assert not result.success
        assert "Unknown tool" in result.output

    @pytest.mark.asyncio
    async def test_close_web_idempotent(self, executor):
        await executor.close_web()
        await executor.close_web()  # second call should not raise


# ---------------------------------------------------------------------------
# AgentToolExecutor fallthrough test
# ---------------------------------------------------------------------------


class TestAgentToolExecutorFallthrough:
    """Web tools fall through AgentToolExecutor to ToolExecutor."""

    @pytest.mark.asyncio
    async def test_web_search_falls_through(self):
        bus = EventBus()
        tool_executor = ToolExecutor(bus)
        agent_executor = AgentToolExecutor(bus, {}, tool_executor)

        tc = ToolCall(
            id="fall-1",
            name="web_search",
            arguments=json.dumps({"query": "test"}),
        )
        result = await agent_executor.execute(tc)
        assert isinstance(result, ToolResult)
        # Falls through to ToolExecutor -> web adapter -> unavailable/error
        lower = result.output.lower()
        assert "unavailable" in lower or "error" in lower
