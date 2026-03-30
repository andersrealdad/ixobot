"""Tests for memory context injection."""

from ixobot.memory.context import build_memory_section
from ixobot.memory.sqlite_store import SqliteMemoryStore


def test_build_memory_section_with_crystals(tmp_path):
    store = SqliteMemoryStore(str(tmp_path / "mem.db"))
    mem_id = store.store({
        "content": "API redesign decided",
        "memory_type": "decision",
        "importance": 0.9,
    })
    store.promote(mem_id, {"content": "API uses REST not GraphQL", "topics": ["architecture"]})

    section = build_memory_section(store)
    assert "## Your Memory" in section
    assert "API uses REST not GraphQL" in section


def test_build_memory_section_with_recent(tmp_path):
    store = SqliteMemoryStore(str(tmp_path / "mem.db"))
    store.store({
        "content": "Deployed new service",
        "memory_type": "observation",
        "importance": 0.6,
    })

    section = build_memory_section(store)
    assert "Recent observations" in section
    assert "Deployed new service" in section


def test_build_memory_section_empty(tmp_path):
    store = SqliteMemoryStore(str(tmp_path / "mem.db"))
    section = build_memory_section(store)
    assert section == ""
