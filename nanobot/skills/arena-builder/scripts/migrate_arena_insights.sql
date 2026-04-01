-- Arena Builder: Insight Harvester migration (Phase 3, HARV-02/HARV-03)
-- Creates the arena_build_insights table in the ixonaut schema.
-- Stores structured insights from arena competitor runs for training dataset.

CREATE TABLE IF NOT EXISTS ixonaut.arena_build_insights (
    id SERIAL PRIMARY KEY,
    bo_id TEXT NOT NULL,
    model TEXT NOT NULL,
    insight_type TEXT NOT NULL,
    text TEXT NOT NULL,
    edges JSONB DEFAULT '[]'::jsonb,
    severity TEXT NOT NULL DEFAULT 'info',
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    builder_identity TEXT NOT NULL,
    harvested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_arena_insights_bo_id ON ixonaut.arena_build_insights(bo_id);
CREATE INDEX IF NOT EXISTS idx_arena_insights_model ON ixonaut.arena_build_insights(model);
CREATE INDEX IF NOT EXISTS idx_arena_insights_bo_model ON ixonaut.arena_build_insights(bo_id, model);
