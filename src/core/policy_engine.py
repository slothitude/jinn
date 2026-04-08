import re

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
    # ORCHESTRATOR — keyword triggers
    {"intent": "multi-agent", "agent": "ORCHESTRATOR", "model_route": "opus", "memory_strategy": "deep", "threshold": 0.7},
    {"intent": "hierarchy", "agent": "ORCHESTRATOR", "model_route": "opus", "memory_strategy": "deep", "threshold": 0.7},
    {"intent": "delegate", "agent": "ORCHESTRATOR", "model_route": "opus", "memory_strategy": "deep"},
    {"intent": "parallel", "agent": "ORCHESTRATOR", "model_route": "opus", "memory_strategy": "deep"},
    # ORCHESTRATOR — natural language multi-task triggers
    {"intent": "at the same time", "agent": "ORCHESTRATOR", "model_route": "opus", "memory_strategy": "deep"},
    {"intent": "all of these", "agent": "ORCHESTRATOR", "model_route": "opus", "memory_strategy": "deep"},
    {"intent": "in parallel", "agent": "ORCHESTRATOR", "model_route": "opus", "memory_strategy": "deep"},
    {"intent": "and also", "agent": "ORCHESTRATOR", "model_route": "opus", "memory_strategy": "deep"},
    {"intent": "each of the following", "agent": "ORCHESTRATOR", "model_route": "opus", "memory_strategy": "deep"},
]

_HIGH_COMPLEXITY_TOKENS = frozenset([
    "architecture", "distributed", "caching", "migration", "full-stack",
    "security audit", "database design", "system design", "microservice",
    "pipeline", "infrastructure", "scalab", "deploy", "orchestrat",
    "refactor", "redesign", "overhaul",
    "multi-agent", "hierarchy", "delegate", "parallel",
])

# Patterns for structural multi-part detection
_MULTI_PART_PATTERNS = [
    r'(?:first|second|third|1\.|2\.|3\.)',
    r'(?:also|additionally|moreover|furthermore)',
    r'(?:and then|after that|once that)',
]


class PolicyEngine:
    """L3 Decision Plane — routes requests to agents + selects model + memory strategy."""

    async def calculate_complexity(self, text: str) -> float:
        """Heuristic: keyword presence (primary) + length (soft proxy)."""
        lower = text.lower()
        keyword_hits = sum(1 for t in _HIGH_COMPLEXITY_TOKENS if t in lower)
        keyword_score = min(keyword_hits * 0.2, 0.6)
        length_score = 0.1 if len(text) > 200 else 0.0
        return min(0.1 + keyword_score + length_score, 1.0)

    async def _detect_multi_part(self, text: str) -> bool:
        """Detect multi-part requests via structural patterns."""
        lower = text.lower()
        hits = sum(1 for p in _MULTI_PART_PATTERNS if re.search(p, lower))
        parts = [s.strip() for s in re.split(r'[,;]', text) if len(s.strip()) > 10]
        return hits >= 2 or len(parts) >= 3

    async def decide(self, request: AgentRequest) -> PolicyDecision:
        text = request.input_text.lower()
        complexity = await self.calculate_complexity(text)

        agent_id = "BUDDY"
        model_route = "sonnet"
        memory_strategy = "standard"
        provider_override = None
        model_override = None

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

        # Structural multi-part detection -> ORCHESTRATOR
        if agent_id == "BUDDY" and await self._detect_multi_part(text):
            agent_id = "ORCHESTRATOR"
            model_route = "opus"
            memory_strategy = "deep"

        # Fallback to ULTRAPLAN if complexity is very high even without keywords
        if complexity >= 0.9 and agent_id == "BUDDY":
            agent_id = "ULTRAPLAN"
            model_route = "opus"
            memory_strategy = "deep"

        return PolicyDecision(
            agent_id=agent_id,
            model_route=model_route,
            memory_strategy=memory_strategy,
            provider_override=provider_override,
            model_override=model_override,
        )
