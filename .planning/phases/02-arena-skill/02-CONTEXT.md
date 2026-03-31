# Phase 2: Arena Skill - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning
**Source:** Synthesized from Open Brain (thought #187), Phase 1 artifacts, nanobot codebase

<domain>
## Phase Boundary

Build a nanobot skill (`arena-builder`) that picks up arena task_queue entries created by Phase 1's `arena_trigger.py`, runs each competitor in an isolated sandbox using `agent-gsd.sh`, and produces structured `insights.jsonl` output. On completion (or error), post result status to `message_bus`.

This phase does NOT cover insight collection into PostgreSQL (Phase 3) or scoring/ranking (v2).

</domain>

<decisions>
## Implementation Decisions

### Skill Structure
- Skill lives at `nanobot/skills/arena-builder/SKILL.md` with standard nanobot frontmatter
- Skill is NOT user_invocable — it's triggered by heartbeat task pickup, not human `/arena-builder` command
- Skill body tells the agent how to: parse task description JSON, create sandbox, invoke agent-gsd.sh, collect insights, post result

### Task Pickup Integration
- Arena trigger (Phase 1) inserts task_queue rows with `target_agent = "arena-competitor-a"` or `"arena-competitor-b"`
- Nanobot heartbeat (`heartbeat/service.py`) reads `task_queue` WHERE `target_agent = ? AND status = 'pending'`
- The competitor agents are nanobot instances named `arena-competitor-a` and `arena-competitor-b`
- Task `description` field is JSON: `{"bo_id": "...", "bo_filepath": "...", "model": "qwen3-32b|qwen3-8b", "instruks": "..."}`

### Sandbox Isolation
- Each competitor gets its own sandbox directory: `~/shared-data/DEV/garage/workshop/arena-{bo_id}-{model}/`
- Sandbox is created fresh per run — no carryover from previous builds
- Competitor MUST NOT access each other's sandbox or Claude Code's real workspace
- The sandbox gets the stripped instruks written as a file, then `agent-gsd.sh` runs inside it

### Execution via agent-gsd.sh
- `agent-gsd.sh <instruks_file> <result_file> [mode]` — already exists at `~/DEV/garage/infra/octopus/agent-gsd.sh`
- Set `OCTOPUS_MODEL` env var to the assigned model (e.g., `qwen3-32b` or `qwen3-8b`)
- Mode: `quick` (single-phase, light planning) — competitors don't need full autonomous ceremony
- agent-gsd.sh uses OAuth/MAX session — no API key needed
- agent-gsd.sh initializes git repo in sandbox, runs Claude Code CLI

### Insights Format
- Each competitor produces `insights.jsonl` in their sandbox root
- Each line is a JSON object with fields: `type`, `text`, `edges`, `severity`
- `type`: one of `observation`, `decision`, `warning`, `pattern`, `suggestion`
- `edges`: array of strings (related files, concepts, or other insight IDs)
- `severity`: one of `info`, `low`, `medium`, `high`, `critical`
- Additional metadata added by the skill after collection: `bo_id`, `model`, `timestamp`, `builder_identity`

### Result Reporting
- On completion or error, post to `message_bus` table in shared-memory.db
- Message includes: `bo_id`, `model`, `status` (completed/flagged/error), `insight_count`, `duration_s`
- `channel` field: `arena-build`
- `source_agent`: the competitor agent name

### Claude's Discretion
- How to handle agent-gsd.sh failures (timeout, crash) — retry once or mark as error
- Whether to capture stdout/stderr from agent-gsd.sh as supplementary data
- Exact SKILL.md wording and progressive disclosure structure
- How to validate insights.jsonl format before posting result

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 Output (trigger mechanism)
- `~/DEV/garage/infra/octopus/arena_trigger.py` — Creates task_queue rows with competitor JSON payload

### Execution Infrastructure
- `~/DEV/garage/infra/octopus/agent-gsd.sh` — GSD-powered builder agent for sandboxes (modes, env vars, auth)

### Nanobot Skill Pattern
- `nanobot/skills/gsd-config/SKILL.md` — Reference SKILL.md frontmatter and structure
- `nanobot/agent/skills.py` — Skill discovery: workspace > built-in priority, re-scanned per context

### Nanobot Task Pickup
- `nanobot/heartbeat/service.py` — `_fetch_pending_tasks()`, `_claim_task()`, `_format_tasks_for_prompt()`

### Message Bus
- `~/shared-data/db/shared-memory.db` — SQLite: `task_queue` and `message_bus` tables

</canonical_refs>

<specifics>
## Specific Ideas

- Competitors use local models (Qwen via Ollama) — zero API cost
- Competitor timeout should match Octopus default (30 min for GSD mode)
- The skill should be idempotent — if a competitor crashes, the task can be re-queued
- Sandbox cleanup: keep sandbox for Phase 3 insight harvesting, don't delete on completion

</specifics>

<deferred>
## Deferred Ideas

- Insight quality scoring (v2: SCOR-01 through SCOR-03)
- Fine-tuning pipeline from collected insights (v2: TRAIN-01, TRAIN-02)
- Real-time streaming of competitor progress
- Winner auto-selection

</deferred>

---

*Phase: 02-arena-skill*
*Context gathered: 2026-04-01 via Open Brain synthesis*
