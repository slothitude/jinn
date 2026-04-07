"""Tests for hierarchical multi-agent orchestration with parallel batch delegation."""

import asyncio
import json
import pytest

from src.core.bus import EventBus
from src.core.models import (
    AgentState,
    AgentTier,
    DelegationContext,
    DelegationResult,
    Event,
    ToolCall,
    ToolResult,
)
from src.agents.base import BaseAgent
from src.agents.buddy import BuddyAgent
from src.agents.orchestrator import OrchestratorAgent
from src.agents.supervisor import SupervisorAgent
from src.execution.agent_tools import (
    AgentToolExecutor,
    DELEGATE_BATCH_TOOL,
    SPAWN_WORKERS_TOOL,
)
from src.execution.toolbox import ToolExecutor


# --- Helpers ---

class FakeAgent(BaseAgent):
    """Agent that yields a fixed response for testing."""

    def __init__(self, name: str, bus: EventBus, response: str = "done", provider: str | None = None):
        super().__init__(name, bus, provider=provider)
        self._response = response
        self.calls: list[str] = []

    async def execute(self, prompt: str, state: AgentState | None = None):
        self.calls.append(prompt)
        for chunk in self._response.split(" "):
            yield chunk + " "


def _make_bus() -> EventBus:
    return EventBus()


def _make_tool_executor(bus: EventBus) -> ToolExecutor:
    return ToolExecutor(bus)


# --- Tests ---

class TestAgentToolExecutorBatch:
    """Test parallel batch delegation via AgentToolExecutor."""

    @pytest.mark.asyncio
    async def test_delegate_batch_parallel(self):
        """delegate_batch spawns multiple supervisors in parallel."""
        bus = _make_bus()
        fake_supervisor = FakeAgent("SUPERVISOR", bus, response="sup-result")
        te = _make_tool_executor(bus)
        ate = AgentToolExecutor(bus, {"SUPERVISOR": fake_supervisor}, te)

        tool_call = ToolCall(
            id="tc-1",
            name="delegate_batch",
            arguments=json.dumps({
                "tasks": [
                    {"task": "Task A"},
                    {"task": "Task B"},
                    {"task": "Task C"},
                ]
            }),
        )

        result = await ate.execute(tool_call)

        assert result.success
        assert "Agent-0" in result.output
        assert "Agent-1" in result.output
        assert "Agent-2" in result.output
        assert len(fake_supervisor.calls) == 3

    @pytest.mark.asyncio
    async def test_spawn_workers_parallel(self):
        """spawn_workers spawns multiple workers in parallel."""
        bus = _make_bus()
        fake_worker = FakeAgent("BUDDY", bus, response="worker-result")
        te = _make_tool_executor(bus)
        ate = AgentToolExecutor(bus, {"BUDDY": fake_worker}, te)

        tool_call = ToolCall(
            id="tc-2",
            name="spawn_workers",
            arguments=json.dumps({
                "workers": [
                    {"task": "Worker task 1", "acceptance_criteria": "passes"},
                    {"task": "Worker task 2"},
                ]
            }),
        )

        result = await ate.execute(tool_call)

        assert result.success
        assert len(fake_worker.calls) == 2
        # Verify constraints are passed through
        assert "Constraints: passes" in fake_worker.calls[0]

    @pytest.mark.asyncio
    async def test_unknown_tool_falls_through(self):
        """Non-delegation tools are passed to ToolExecutor."""
        bus = _make_bus()
        te = _make_tool_executor(bus)
        ate = AgentToolExecutor(bus, {}, te)

        tool_call = ToolCall(
            id="tc-3",
            name="bash",
            arguments=json.dumps({"command": "echo hello"}),
        )

        result = await ate.execute(tool_call)
        assert result.name == "bash"


class TestContextScoping:
    """Verify fresh AgentState per tier — no context leakage."""

    @pytest.mark.asyncio
    async def test_fresh_state_per_delegation(self):
        """Each delegated task gets a fresh AgentState with empty history."""
        bus = _make_bus()
        received_states: list[AgentState | None] = []

        class StateCaptureAgent(BaseAgent):
            def __init__(self, bus):
                super().__init__("SUPERVISOR", bus)

            async def execute(self, prompt, state=None):
                received_states.append(state)
                yield "captured"

        agent = StateCaptureAgent(bus)
        te = _make_tool_executor(bus)
        ate = AgentToolExecutor(bus, {"SUPERVISOR": agent}, te)

        tool_call = ToolCall(
            id="tc-4",
            name="delegate_batch",
            arguments=json.dumps({"tasks": [{"task": "A"}, {"task": "B"}]}),
        )

        await ate.execute(tool_call)

        assert len(received_states) == 2
        for s in received_states:
            assert s is not None
            assert s.history == []
            assert s.session_id.startswith("del-")

    @pytest.mark.asyncio
    async def test_no_parent_context_leak(self):
        """Parent state history is not visible in delegated states."""
        bus = _make_bus()
        parent_state = AgentState(
            session_id="parent",
            history=[{"user": "secret parent data", "assistant": "secret response"}],
        )

        received_states: list[AgentState | None] = []

        class InspectorAgent(BaseAgent):
            def __init__(self, bus):
                super().__init__("SUPERVISOR", bus)

            async def execute(self, prompt, state=None):
                received_states.append(state)
                yield "ok"

        agent = InspectorAgent(bus)
        te = _make_tool_executor(bus)
        ate = AgentToolExecutor(bus, {"SUPERVISOR": agent}, te)

        tool_call = ToolCall(
            id="tc-5",
            name="delegate_batch",
            arguments=json.dumps({"tasks": [{"task": "check"}]}),
        )

        await ate.execute(tool_call)

        assert len(received_states) == 1
        assert received_states[0].history == []
        assert received_states[0].session_id != parent_state.session_id


class TestMultiProviderRouting:
    """Verify different agents use different providers."""

    def test_orchestrator_default_provider(self):
        """OrchestratorAgent without explicit provider uses default."""
        bus = _make_bus()
        agent = OrchestratorAgent(bus)
        from src.core.provider import default_client
        assert agent._client is default_client

    def test_orchestrator_with_provider(self):
        """OrchestratorAgent with provider='zhipu' uses zhipu client."""
        bus = _make_bus()
        agent = OrchestratorAgent(bus, provider="zhipu")
        from src.core.provider import get_provider_client
        assert agent._client is get_provider_client("zhipu")
        assert agent._provider == "zhipu"

    def test_supervisor_with_provider(self):
        """SupervisorAgent with provider uses specified provider."""
        bus = _make_bus()
        agent = SupervisorAgent(bus, provider="zhipu")
        from src.core.provider import get_provider_client
        assert agent._client is get_provider_client("zhipu")

    def test_base_agent_default_fallback(self):
        """BaseAgent without provider falls back to default client."""
        bus = _make_bus()
        agent = FakeAgent("TEST", bus)
        from src.core.provider import default_client, default_model
        assert agent._client is default_client
        assert agent._model == default_model


class TestDelegationDepth:
    """Test delegation depth enforcement."""

    @pytest.mark.asyncio
    async def test_depth_limit(self):
        """Delegation beyond max depth returns error."""
        bus = _make_bus()
        te = _make_tool_executor(bus)
        ate = AgentToolExecutor(bus, {}, te)
        ate._max_depth = 1

        # First delegation succeeds
        tc1 = ToolCall(
            id="tc-6",
            name="delegate_batch",
            arguments=json.dumps({"tasks": [{"task": "first"}]}),
        )
        # No SUPERVISOR registered, so it'll fail with "not registered"
        result = await ate.execute(tc1)
        assert not result.success  # No SUPERVISOR agent registered

        # At depth limit, returns depth error
        ate._delegation_depth = 1
        tc2 = ToolCall(
            id="tc-7",
            name="delegate_batch",
            arguments=json.dumps({"tasks": [{"task": "too deep"}]}),
        )
        result = await ate.execute(tc2)
        assert "depth limit" in result.output.lower()

    @pytest.mark.asyncio
    async def test_empty_tasks(self):
        """Empty task array returns error."""
        bus = _make_bus()
        te = _make_tool_executor(bus)
        ate = AgentToolExecutor(bus, {}, te)

        tc = ToolCall(
            id="tc-8",
            name="delegate_batch",
            arguments=json.dumps({"tasks": []}),
        )
        result = await ate.execute(tc)
        assert not result.success
        assert "no tasks" in result.output.lower()


class TestDelegationEvents:
    """Test DELEGATION_START and DELEGATION_END events."""

    @pytest.mark.asyncio
    async def test_events_emitted(self):
        """Delegation emits DELEGATION_START and DELEGATION_END events."""
        bus = _make_bus()
        fake_supervisor = FakeAgent("SUPERVISOR", bus, response="result")
        te = _make_tool_executor(bus)
        ate = AgentToolExecutor(bus, {"SUPERVISOR": fake_supervisor}, te)

        events: list[tuple[str, dict]] = []

        async def capture(event_type, payload):
            events.append((event_type, payload))

        bus.subscribe(Event.DELEGATION_START, lambda p: capture("start", p))
        bus.subscribe(Event.DELEGATION_END, lambda p: capture("end", p))

        tc = ToolCall(
            id="tc-9",
            name="delegate_batch",
            arguments=json.dumps({"tasks": [{"task": "emit test"}]}),
        )

        await ate.execute(tc)

        event_types = [e[0] for e in events]
        assert "start" in event_types
        assert "end" in event_types


class TestFullThreeTierChain:
    """End-to-end test: ORCHESTRATOR → SUPERVISOR → WORKER."""

    @pytest.mark.asyncio
    async def test_three_tier_chain(self):
        """Full 3-tier delegation with mocked LLM."""
        bus = _make_bus()

        # Tier 2: Workers (BUDDY)
        worker = FakeAgent("BUDDY", bus, response="worker output")

        # Tier 1: Supervisor
        supervisor = SupervisorAgent(bus, provider=None)
        te = _make_tool_executor(bus)
        ate = AgentToolExecutor(bus, {"BUDDY": worker}, te)
        supervisor.set_agent_tool_executor(ate)

        # Tier 0: Orchestrator
        orchestrator = OrchestratorAgent(bus, provider=None)
        ate2 = AgentToolExecutor(bus, {"SUPERVISOR": supervisor}, te)
        orchestrator.set_agent_tool_executor(ate2)

        # Simulate orchestrator calling delegate_batch
        tc = ToolCall(
            id="tc-10",
            name="delegate_batch",
            arguments=json.dumps({
                "tasks": [
                    {"task": "Implement feature A", "supervisor_type": "code"},
                    {"task": "Write tests for A", "supervisor_type": "testing"},
                ]
            }),
        )

        # The supervisor's execute is called directly (bypassing its tool loop)
        # because it won't have an LLM to call spawn_workers.
        # Test the delegation bridge directly:
        result = await ate2.execute(tc)

        assert result.success
        assert "Agent-0" in result.output
        assert "Agent-1" in result.output


class TestNewModels:
    """Test new data models."""

    def test_agent_tier_enum(self):
        assert AgentTier.ORCHESTRATOR == "orchestrator"
        assert AgentTier.SUPERVISOR == "supervisor"
        assert AgentTier.WORKER == "worker"

    def test_delegation_context_defaults(self):
        ctx = DelegationContext(task_description="test task")
        assert ctx.constraints == ""
        assert ctx.tier == AgentTier.SUPERVISOR
        assert ctx.provider == "zhipu"

    def test_delegation_result_defaults(self):
        r = DelegationResult(success=True, output="ok")
        assert r.errors == []

    def test_delegation_events_in_enum(self):
        assert Event.DELEGATION_START == "delegation_start"
        assert Event.DELEGATION_END == "delegation_end"


class TestToolSchemas:
    """Test delegation tool schema formats."""

    def test_delegate_batch_schema(self):
        fmt = DELEGATE_BATCH_TOOL.to_openai_format()
        assert fmt["type"] == "function"
        assert fmt["function"]["name"] == "delegate_batch"
        assert "tasks" in fmt["function"]["parameters"]["properties"]

    def test_spawn_workers_schema(self):
        fmt = SPAWN_WORKERS_TOOL.to_openai_format()
        assert fmt["type"] == "function"
        assert fmt["function"]["name"] == "spawn_workers"
        assert "workers" in fmt["function"]["parameters"]["properties"]
