import tempfile
from pathlib import Path

import pytest

from src.memory.schema import MemoryUnit
from src.memory.store import MemoryStore
from src.memory.ranking import rank, _recency_score, _relevance_score
from src.memory.retrieval import retrieve


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(db_path=tmp_path / "test_memory.db")
    yield s
    s.close()


def test_put_and_get(store):
    m = MemoryUnit(summary="Test memory", tags=["preference"], importance=0.8)
    store.put(m)
    result = store.get(m.id)
    assert result is not None
    assert result.summary == "Test memory"
    assert result.tags == ["preference"]


def test_get_all(store):
    for i in range(5):
        store.put(MemoryUnit(summary=f"Memory {i}", tags=["preference"]))
    results = store.get_all()
    assert len(results) == 5


def test_search_by_tag(store):
    store.put(MemoryUnit(summary="Pref", tags=["preference"]))
    store.put(MemoryUnit(summary="Constr", tags=["constraint"]))
    results = store.search_by_tag("preference")
    assert len(results) == 1
    assert results[0].summary == "Pref"


def test_delete(store):
    m = MemoryUnit(summary="To delete", tags=["test"])
    store.put(m)
    store.delete(m.id)
    assert store.get(m.id) is None


def test_update_access(store):
    m = MemoryUnit(summary="Access test", tags=["test"])
    store.put(m)
    store.update_access(m.id)
    result = store.get(m.id)
    assert result.access_count == 1


def test_rank_orders_by_composite():
    memories = [
        MemoryUnit(summary="low importance", tags=["preference"], importance=0.1),
        MemoryUnit(summary="high importance", tags=["preference"], importance=0.9),
        MemoryUnit(summary="medium importance", tags=["preference"], importance=0.5),
    ]
    ranked = rank(memories, query="importance")
    assert ranked[0].summary == "high importance"


def test_relevance_score():
    m = MemoryUnit(summary="python debug tools")
    score = _relevance_score(m, "debug python code")
    assert score > 0


def test_recency_score():
    import time
    recent = _recency_score(time.time())
    old = _recency_score(time.time() - 86400 * 30)  # 30 days ago
    assert recent > old


@pytest.mark.asyncio
async def test_retrieve_filters_by_role(store):
    store.put(MemoryUnit(summary="User preference", tags=["preference"], importance=0.8))
    store.put(MemoryUnit(summary="Constraint rule", tags=["constraint"], importance=0.9))
    store.put(MemoryUnit(summary="Past failure", tags=["failure"], importance=0.7))

    buddy_results = await retrieve("test", "buddy", store, k=10)
    assert all("preference" in m.tags or "heuristic" in m.tags for m in buddy_results)

    ultraplan_results = await retrieve("test", "ultraplan", store, k=10)
    assert all("constraint" in m.tags or "failure" in m.tags for m in ultraplan_results)
