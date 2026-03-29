CREATE TABLE IF NOT EXISTS memories (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    summary     TEXT,
    memory_type TEXT NOT NULL,
    importance  REAL DEFAULT 0.5,
    decay_score REAL DEFAULT 1.0,
    source      TEXT,
    agent_name  TEXT,
    metadata    TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    promoted_at TEXT
);

CREATE TABLE IF NOT EXISTS crystals (
    id          TEXT PRIMARY KEY,
    memory_id   TEXT REFERENCES memories(id),
    content     TEXT NOT NULL,
    topics      TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_decay ON memories(decay_score DESC);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_crystals_created ON crystals(created_at DESC);
