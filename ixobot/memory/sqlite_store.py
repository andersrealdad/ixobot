"""SQLite backend for IxoBot persistent memory."""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from ixobot.memory.store import PersistentMemoryStore

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class SqliteMemoryStore(PersistentMemoryStore):
    """Zero-config SQLite memory backend. Default for standalone IxoBot."""

    def __init__(self, db_path: str = "~/.ixobot/memory.db"):
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        schema = _SCHEMA_PATH.read_text()
        conn = self._connect()
        conn.executescript(schema)
        conn.close()

    def store(self, memory: dict) -> str:
        mem_id = f"mem:{uuid.uuid4().hex[:16]}"
        conn = self._connect()
        conn.execute(
            """INSERT INTO memories (id, content, summary, memory_type, importance,
               source, agent_name, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mem_id,
                memory["content"],
                memory.get("summary"),
                memory["memory_type"],
                memory.get("importance", 0.5),
                memory.get("source"),
                memory.get("agent_name"),
                json.dumps(memory.get("metadata")) if memory.get("metadata") else None,
            ),
        )
        conn.commit()
        conn.close()
        return mem_id

    def query(
        self,
        limit: int = 20,
        importance_min: float = 0.0,
        memory_type: Optional[str] = None,
    ) -> list[dict]:
        conn = self._connect()
        sql = "SELECT * FROM memories WHERE importance >= ?"
        params: list = [importance_min]

        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type)

        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def promote(self, memory_id: str, crystal: dict) -> None:
        crystal_id = f"crystal:{uuid.uuid4().hex[:16]}"
        conn = self._connect()
        conn.execute(
            "INSERT INTO crystals (id, memory_id, content, topics) VALUES (?, ?, ?, ?)",
            (
                crystal_id,
                memory_id,
                crystal["content"],
                json.dumps(crystal.get("topics", [])),
            ),
        )
        conn.execute(
            "UPDATE memories SET promoted_at = datetime('now') WHERE id = ?",
            (memory_id,),
        )
        conn.commit()
        conn.close()

    def get_crystals(self, limit: int = 10) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM crystals ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def decay(self, rate: float = 0.01) -> int:
        conn = self._connect()
        cur = conn.execute(
            """UPDATE memories
               SET decay_score = MAX(0.0, decay_score - ?)
               WHERE promoted_at IS NULL AND decay_score > 0.0""",
            (rate,),
        )
        affected = cur.rowcount
        conn.commit()
        conn.close()
        return affected
