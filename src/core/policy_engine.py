from src.core.models import AgentRequest, PolicyDecision

POLICY_RULES = [
    {"intent": "plan", "agent": "ULTRAPLAN", "model_route": "opus", "memory_strategy": "deep", "threshold": 0.8},
    {"intent": "architect", "agent": "ULTRAPLAN", "model_route": "opus", "memory_strategy": "deep", "threshold": 0.8},
    {"intent": "design", "agent": "ULTRAPLAN", "model_route": "opus", "memory_strategy": "deep", "threshold": 0.7},
    {"intent": "code", "agent": "BUDDY", "model_route": "sonnet", "memory_strategy": "standard"},
    {"intent": "refactor", "agent": "BUDDY", "model_route": "sonnet", "memory_strategy": "standard"},
    {"intent": "explain", "agent": "BUDDY", "model_route": "sonnet", "memory_strategy": "standard"},
    {"intent": "debug", "agent": "BUDDY", "model_route": "sonnet", "memory_strategy": "failures"},
    {"intent": "fix", "agent": "BUDDY", "model_route": "sonnet", "memory_strategy": "failures"},
    {"intent": "monitor", "agent": "KAIROS", "model_route": "haiku", "memory_strategy": "anomalies"},
    {"intent": "watch", "agent": "KAIROS", "model_route": "haiku", "memory_strategy": "anomalies"},
]

_HIGH_COMPLEXITY_TOKENS = frozenset([
    "architecture", "distributed", "caching", "migration", "full-stack",
    "security audit", "database design", "system design", "microservice",
    "pipeline", "infrastructure", "scalab", "deploy", "orchestrat",
    "refactor", "redesign", "overhaul",
])


class PolicyEngine:
    """L3 Decision Plane — routes requests to agents + selects model + memory strategy."""

    async def calculate_complexity(self, text: str) -> float:
        """Heuristic: keyword presence (primary) + length (soft proxy)."""
        lower = text.lower()
        keyword_hits = sum(1 for t in _HIGH_COMPLEXITY_TOKENS if t in lower)
        keyword_score = min(keyword_hits * 0.2, 0.6)
        length_score = 0.1 if len(text) > 200 else 0.0
        return min(0.1 + keyword_score + length_score, 1.0)

    async def decide(self, request: AgentRequest) -> PolicyDecision:
        text = request.input_text.lower()
        complexity = await self.calculate_complexity(text)
        
        agent_id = "BUDDY"
        model_route = "sonnet"
        memory_strategy = "standard"

        for rule in POLICY_RULES:
            # If a rule has a threshold, it must meet it.
            # Otherwise, keyword match is sufficient.
            if rule["intent"] in text:
                if "threshold" in rule:
                    if complexity >= rule["threshold"]:
                        agent_id = rule["agent"]
                        model_route = rule["model_route"]
                        memory_strategy = rule["memory_strategy"]
                        break
                    else:
                        # Continue to see if other rules match
                        continue
                else:
                    agent_id = rule["agent"]
                    model_route = rule["model_route"]
                    memory_strategy = rule["memory_strategy"]
                    break
        
        # Fallback to ULTRAPLAN if complexity is very high even without keywords
        if complexity >= 0.9 and agent_id == "BUDDY":
            agent_id = "ULTRAPLAN"
            model_route = "opus"
            memory_strategy = "deep"

        return PolicyDecision(
            agent_id=agent_id,
            model_route=model_route,
            memory_strategy=memory_strategy,
        )
