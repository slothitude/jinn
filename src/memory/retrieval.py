from typing import List, Optional

from src.memory.schema import MemoryUnit
from src.memory.store import MemoryStore
from src.memory.ranking import rank

# Role-to-tag mapping — each agent sees relevant memory types
ROLE_TAG_MAP = {
    "buddy": ["preference", "heuristic"],
    "kairos": ["constraint", "anomaly"],
    "ultraplan": ["constraint", "failure"],
    "standard": ["preference", "heuristic"],
    "failures": ["failure"],
    "anomalies": ["anomaly"],
    "deep": ["constraint", "failure", "preference", "heuristic"],
}


async def retrieve(
    query: str,
    agent_role: str,
    store: MemoryStore,
    k: int = 15,
) -> List[MemoryUnit]:
    """Retrieve and rank memories for a given agent role.

    Pipeline:
    1. Fetch candidates from store
    2. Filter by role-relevant tags
    3. Rank by composite score
    4. Return top-k
    """
    candidates = store.get_all(limit=200)
    relevant_tags = ROLE_TAG_MAP.get(agent_role, ["preference", "heuristic"])

    filtered = [
        m for m in candidates if any(tag in m.tags for tag in relevant_tags)
    ]

    ranked = rank(filtered, query=query)
    return ranked[:k]
