from src.core.models import AgentRequest, PolicyDecision

POLICY_RULES = [
    {"intent": "plan", "agent": "ULTRAPLAN", "model_route": "opus", "memory_strategy": "deep", "threshold": 0.8},
    {"intent": "code", "agent": "BUDDY", "model_route": "sonnet", "memory_strategy": "standard"},
    {"intent": "debug", "agent": "BUDDY", "model_route": "sonnet", "memory_strategy": "failures"},
    {"intent": "monitor", "agent": "KAIROS", "model_route": "haiku", "memory_strategy": "anomalies"},
    {"intent": "watch", "agent": "KAIROS", "model_route": "haiku", "memory_strategy": "anomalies"},
]


class PolicyEngine:
    """L3 Decision Plane — routes requests to agents + selects model + memory strategy."""

    async def calculate_complexity(self, text: str) -> float:
        """Simple heuristic: length + keywords like 'architecture', 'full-stack', 'migration'."""
        keywords = ['complex', 'architecture', 'database design', 'security audit', 'migration', 'full-stack']
        score = 0.1
        if len(text) > 500:
            score += 0.3
        if any(k in text.lower() for k in keywords):
            score += 0.4
        return min(score, 1.0)

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
