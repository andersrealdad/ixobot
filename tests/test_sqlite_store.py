"""Tests for IxoBot persistent memory (SQLite backend)."""

import pytest
from ixobot.memory.sqlite_store import SqliteMemoryStore


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test_memory.db"
    return SqliteMemoryStore(str(db_path))


def test_store_and_query(store):
    mem_id = store.store({
        "content": "Agent discovered a new API endpoint",
        "summary": "New API endpoint found",
        "memory_type": "observation",
        "importance": 0.7,
        "source": "matrix:general",
        "agent_name": "test-agent",
    })
    assert mem_id is not None

    results = store.query(limit=10)
    assert len(results) == 1
    assert results[0]["content"] == "Agent discovered a new API endpoint"
    assert results[0]["importance"] == 0.7


def test_query_filters_by_importance(store):
    store.store({"content": "low", "memory_type": "observation", "importance": 0.2})
    store.store({"content": "high", "memory_type": "observation", "importance": 0.9})

    results = store.query(importance_min=0.5)
    assert len(results) == 1
    assert results[0]["content"] == "high"


def test_query_filters_by_type(store):
    store.store({"content": "a decision", "memory_type": "decision", "importance": 0.5})
    store.store({"content": "a lesson", "memory_type": "lesson", "importance": 0.5})

    results = store.query(memory_type="decision")
    assert len(results) == 1
    assert results[0]["content"] == "a decision"


def test_promote_and_get_crystals(store):
    mem_id = store.store({
        "content": "important pattern",
        "memory_type": "observation",
        "importance": 0.9,
    })

    store.promote(mem_id, {"content": "Synthesized crystal insight", "topics": ["patterns"]})

    crystals = store.get_crystals(limit=10)
    assert len(crystals) == 1
    assert crystals[0]["content"] == "Synthesized crystal insight"
    assert crystals[0]["memory_id"] == mem_id


def test_decay_reduces_scores(store):
    store.store({"content": "will decay", "memory_type": "observation", "importance": 0.5})

    decayed = store.decay(rate=0.1)
    assert decayed == 1

    results = store.query()
    assert results[0]["decay_score"] < 1.0


def test_decay_skips_promoted(store):
    mem_id = store.store({"content": "promoted", "memory_type": "observation", "importance": 0.9})
    store.promote(mem_id, {"content": "crystal", "topics": []})

    decayed = store.decay(rate=0.1)
    assert decayed == 0


def test_empty_query(store):
    results = store.query()
    assert results == []
    crystals = store.get_crystals()
    assert crystals == []
