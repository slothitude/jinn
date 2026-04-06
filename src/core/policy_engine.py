from src.core.models import AgentRequest, PolicyDecision

POLICY_RULES = [
    {"intent": "plan", "agent": "ULTRAPLAN", "model_route": "opus", "memory_strategy": "deep"},
    {"intent": "code", "agent": "BUDDY", "model_route": "sonnet", "memory_strategy": "standard"},
    {"intent": "debug", "agent": "BUDDY", "model_route": "sonnet", "memory_strategy": "failures"},
    {"intent": "monitor", "agent": "KAIROS", "model_route": "haiku", "memory_strategy": "anomalies"},
    {"intent": "watch", "agent": "KAIROS", "model_route": "haiku", "memory_strategy": "anomalies"},
]


class PolicyEngine:
    """L3 Decision Plane — routes requests to agents + selects model + memory strategy."""

    async def decide(self, request: AgentRequest) -> PolicyDecision:
        text = request.input_text.lower()
        agent_id = "BUDDY"
        model_route = "sonnet"
        memory_strategy = "standard"

        for rule in POLICY_RULES:
            if rule["intent"] in text:
                agent_id = rule["agent"]
                model_route = rule["model_route"]
                memory_strategy = rule["memory_strategy"]
                break

        return PolicyDecision(
            agent_id=agent_id,
            model_route=model_route,
            memory_strategy=memory_strategy,
        )
