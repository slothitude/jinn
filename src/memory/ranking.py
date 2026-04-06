import math
import time
from typing import List, Optional

from src.memory.schema import MemoryUnit


def _recency_score(last_used: float, now: Optional[float] = None) -> float:
    """Exponential decay — more recent memories score higher."""
    if now is None:
        now = time.time()
    age_hours = (now - last_used) / 3600
    return math.exp(-0.1 * age_hours)


def _relevance_score(memory: MemoryUnit, query: str) -> float:
    """Simple text overlap relevance — placeholder for embedding similarity."""
    if not query:
        return 0.5
    query_words = set(query.lower().split())
    summary_words = set(memory.summary.lower().split())
    if not query_words:
        return 0.5
    overlap = len(query_words & summary_words)
    return min(overlap / max(len(query_words), 1), 1.0)


def _policy_score(tags: list[str]) -> float:
    """Boost constraint and failure memories — they prevent repeated mistakes."""
    high_priority_tags = {"constraint", "failure"}
    if any(t in high_priority_tags for t in tags):
        return 1.0
    return 0.5


def rank(
    candidates: List[MemoryUnit],
    query: str = "",
    relevance_w: float = 0.4,
    importance_w: float = 0.3,
    recency_w: float = 0.2,
    policy_w: float = 0.1,
) -> List[MemoryUnit]:
    """Score and sort memories by composite of relevance, importance, recency, policy."""
    now = time.time()
    for m in candidates:
        r = _relevance_score(m, query)
        rec = _recency_score(m.last_used, now)
        p = _policy_score(m.tags)
        m.importance = (
            relevance_w * r + importance_w * m.importance + recency_w * rec + policy_w * p
        )
    return sorted(candidates, key=lambda m: m.importance, reverse=True)
