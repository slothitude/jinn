from typing import List, Optional

from src.memory.schema import MemoryUnit
from src.memory.store import MemoryStore
from src.memory.wiki import WikiStore
from src.memory.ranking import rank

# Role-to-tag mapping — each agent sees relevant memory types
ROLE_TAG_MAP = {
    "buddy": ["preference", "heuristic", "lesson"],
    "kairos": ["constraint", "anomaly"],
    "ultraplan": ["constraint", "failure", "lesson"],
    "orchestrator": ["constraint", "lesson"],
    "supervisor": ["preference", "heuristic", "lesson"],
    "standard": ["preference", "heuristic", "lesson"],
    "failures": ["failure"],
    "anomalies": ["anomaly"],
    "deep": ["constraint", "failure", "preference", "heuristic", "lesson"],
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


async def retrieve_with_wiki(
    query: str,
    agent_role: str,
    store: MemoryStore,
    wiki_store: WikiStore,
    k: int = 15,
) -> dict:
    """Retrieve memories + wiki pages with category boosting.

    Returns {"memories": [...], "wiki_pages": [...], "wiki_index": {...}}
    """
    memories = await retrieve(query, agent_role, store, k)

    # Search wiki pages
    wiki_pages = wiki_store.search(query, limit=10)

    # Category boosting: if a category name appears in the query, boost those pages
    query_lower = query.lower()
    index = wiki_store.get_index()
    boosted = []
    rest = []

    for page in wiki_pages:
        if page.category.lower() in query_lower:
            boosted.append(page)
        else:
            rest.append(page)

    # Boosted pages first, then rest, limited to 5
    ranked_pages = boosted + rest
    ranked_pages = ranked_pages[:5]

    return {
        "memories": memories,
        "wiki_pages": [p.to_dict() for p in ranked_pages],
        "wiki_index": index,
    }
