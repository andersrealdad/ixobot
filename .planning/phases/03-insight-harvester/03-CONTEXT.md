# Phase 3: Insight Harvester - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning
**Source:** Infrastructure phase — smart discuss (minimal context)

<domain>
## Phase Boundary

Collect insights.jsonl files from all arena competitor sandboxes after a BO completes, store them in PostgreSQL (`ixonaut.arena_build_insights` on stacks:5432), and post a per-model comparison summary to message_bus channel `arena-build`.

This phase does NOT cover scoring, ranking, or fine-tuning (v2 scope).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pure infrastructure phase.

Key integration points from prior phases:
- Phase 2 arena_run.py already posts individual result status to message_bus and writes insights.jsonl per competitor
- Phase 3 needs a collector that runs AFTER all competitors finish a given BO — detect completion via message_bus rows for the same bo_id
- PostgreSQL connection uses `stacks:5432`, db `astrid_memory`, schema `ixonaut`, user `astrid` (vault: `postgres-credentials`)
- The `ixonaut.arena_build_insights` table must be created (migration script or inline CREATE TABLE)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 2 Output (insights producer)
- `nanobot/skills/arena-builder/scripts/arena_run.py` — Writes insights.jsonl per competitor, posts to message_bus
- `nanobot/skills/arena-builder/SKILL.md` — Documents the insights.jsonl format and message_bus posting

### Database
- PostgreSQL on stacks:5432, db: `astrid_memory`, schema: `ixonaut`
- Secrets via `~/bin/bw-fetch-secret postgres-credentials` or `secrets_client.get_secret("postgres-credentials")`

### Message Bus
- `~/shared-data/db/shared-memory.db` — SQLite: `message_bus` table, channel `arena-build`

</canonical_refs>

<specifics>
## Specific Ideas

No specific requirements — infrastructure phase

</specifics>

<deferred>
## Deferred Ideas

- Insight quality scoring (v2: SCOR-01 through SCOR-03)
- Fine-tuning pipeline export (v2: TRAIN-01, TRAIN-02)
- Cross-BO insight aggregation and trend detection

</deferred>

---

*Phase: 03-insight-harvester*
*Context gathered: 2026-04-01 via smart discuss (infrastructure phase)*
