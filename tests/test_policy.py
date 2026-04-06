import pytest

from src.core.models import AgentRequest
from src.core.policy_engine import PolicyEngine
from src.core.bus import EventBus
from src.core.query_engine import QueryEngine
from src.agents.buddy import BuddyAgent
from src.agents.ultraplan import UltraplanAgent
from src.agents.kairos import KairosAgent


@pytest.mark.asyncio
async def test_policy_routes_to_ultraplan():
    engine = PolicyEngine()
    req = AgentRequest(session_id="test", input_text="write a plan for the complex architecture migration of our full-stack database design and security audit. " + "We need a comprehensive strategy covering database schema migration, full-stack application changes, security audit procedures, and rollback mechanisms. " * 10)
    decision = await engine.decide(req)
    assert decision.agent_id == "ULTRAPLAN"
    assert decision.model_route == "opus"


@pytest.mark.asyncio
async def test_policy_routes_to_buddy_code():
    engine = PolicyEngine()
    req = AgentRequest(session_id="test", input_text="write code to parse CSV")
    decision = await engine.decide(req)
    assert decision.agent_id == "BUDDY"
    assert decision.model_route == "sonnet"


@pytest.mark.asyncio
async def test_policy_routes_to_buddy_debug():
    engine = PolicyEngine()
    req = AgentRequest(session_id="test", input_text="fix this debug issue")
    decision = await engine.decide(req)
    assert decision.agent_id == "BUDDY"
    assert decision.memory_strategy == "failures"


@pytest.mark.asyncio
async def test_policy_routes_to_kairos():
    engine = PolicyEngine()
    req = AgentRequest(session_id="test", input_text="monitor the deployment")
    decision = await engine.decide(req)
    assert decision.agent_id == "KAIROS"
    assert decision.model_route == "haiku"


@pytest.mark.asyncio
async def test_policy_default_is_buddy():
    engine = PolicyEngine()
    req = AgentRequest(session_id="test", input_text="hello what's up")
    decision = await engine.decide(req)
    assert decision.agent_id == "BUDDY"


@pytest.mark.asyncio
async def test_query_engine_full_pipeline():
    bus = EventBus()
    engine = QueryEngine(bus)
    engine.register_agent(BuddyAgent(bus))
    engine.register_agent(UltraplanAgent(bus))
    engine.register_agent(KairosAgent(bus))

    from src.core.models import AgentState
    state = AgentState(session_id="test-pipeline")
    request = AgentRequest(session_id="test-pipeline", input_text="write some code")

    response = await engine.process(request, state)
    assert "BUDDY" in response
    assert state.turn_count == 1
    assert len(state.history) == 1
