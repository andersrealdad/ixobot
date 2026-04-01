# Roadmap: Arena Builder

## Overview

Turn every Build Order into a model competition. Phase 1 wires the trigger so IxoGSD pre-flight spawns arena tasks and aligns the repo naming. Phase 2 builds the nanobot skill that runs competitors in isolated sandboxes. Phase 3 collects all insights into PostgreSQL and posts comparison summaries.

## Phases

- [x] **Phase 1: Trigger + Naming** - IxoGSD hook spawns arena tasks on BO claim; repo naming aligned
- [x] **Phase 2: Arena Skill** - Nanobot skill runs two competitors in sandboxes via agent-gsd.sh
- [x] **Phase 3: Insight Harvester** - Collect, store, and report insights from all builders
- [ ] **Phase 4: Arena Provisioning** - Create competitor agent instances and fix SQL escaping
- [ ] **Phase 5: Ops Polish** - Schedule harvester, fix traceability table, NAME-01 checkbox

## Phase Details

### Phase 1: Trigger + Naming
**Goal**: Claiming a BO automatically creates arena competitor tasks without blocking Claude Code
**Depends on**: Nothing (first phase)
**Requirements**: TRIG-01, TRIG-02, TRIG-03, NAME-01
**Success Criteria** (what must be TRUE):
  1. When IxoGSD pre-flight claims a BO, two task_queue entries appear targeting arena competitors
  2. Each task contains the BO ID, stripped instruks, and assigned model (qwen3-32b / qwen3-8b)
  3. Claude Code continues building immediately after trigger fires (no wait, no slowdown)
  4. Local directory and git remote reference a consistent name (ixobot or ixosynth, not mismatched)
**Plans:** 2 plans

Plans:
- [x] 01-01-PLAN.md -- Arena trigger: create arena_trigger.py and wire into preflight.sh
- [x] 01-02-PLAN.md -- Naming alignment: decide and execute repo naming strategy

### Phase 2: Arena Skill
**Goal**: Nanobot agents can execute a Build Order in an isolated sandbox and produce structured insights
**Depends on**: Phase 1
**Requirements**: SKIL-01, SKIL-02, SKIL-03, SKIL-04, SKIL-05
**Success Criteria** (what must be TRUE):
  1. A nanobot skill directory exists at `nanobot/skills/arena-builder/SKILL.md` with correct frontmatter
  2. Each competitor runs in its own sandbox at `~/shared-data/DEV/garage/workshop/arena-{bo_id}-{model}/` with no cross-access
  3. Running the skill invokes `agent-gsd.sh` with the correct `OCTOPUS_MODEL` override for the assigned model
  4. Each competitor produces an `insights.jsonl` file with entries containing type, text, edges, severity fields
  5. On completion (or error), the competitor posts its result status to message_bus
**Plans**: 2 plans

Plans:
- [x] 02-01-PLAN.md -- Create arena-builder SKILL.md and arena_run.py execution script
- [x] 02-02-PLAN.md -- Add dry-run mode, verify message_bus posting, integration test

### Phase 3: Insight Harvester
**Goal**: All builder insights are collected, stored in PostgreSQL, and summarized for human review
**Depends on**: Phase 2
**Requirements**: HARV-01, HARV-02, HARV-03, HARV-04
**Success Criteria** (what must be TRUE):
  1. After all competitors finish a BO, their insights.jsonl files are collected into a single dataset
  2. Insights are stored in `ixonaut.arena_build_insights` table on stacks:5432
  3. Each row includes bo_id, model, insight_type, text, edges, severity, timestamp, builder_identity
  4. A summary message comparing per-model insights is posted to message_bus channel `arena-build`
**Plans**: 2 plans

Plans:
- [x] 03-01-PLAN.md -- PostgreSQL migration + harvest_insights.py collector script
- [x] 03-02-PLAN.md -- Per-model comparison summary posting + integration test

### Phase 4: Arena Provisioning
**Goal**: Arena competitor agents exist as running nanobot instances that can pick up task_queue entries
**Depends on**: Phase 2
**Requirements**: PROV-01, PROV-02, PROV-03
**Gap Closure:** Closes tech debt from v1.0 audit
**Success Criteria** (what must be TRUE):
  1. Agent runtime configs exist at `~/agents/arena-competitor-a/config.json` and `~/agents/arena-competitor-b/config.json`
  2. Agent identity directories exist at `~/DEV/operations/agent-homes/arena-competitor-a/` and `arena-competitor-b/` with minimal SOUL.md
  3. harvest_insights.py uses parameterized SQL (no string interpolation of bo_id/model/severity)
**Plans**: 2 plans

Plans:
- [x] 04-01-PLAN.md -- Agent provisioning: create runtime configs and identity directories for arena-competitor-a/b
- [x] 04-02-PLAN.md -- SQL injection fix: parameterized SQL in harvest_insights.py

### Phase 5: Ops Polish
**Goal**: Operational completeness — harvester runs automatically, traceability is accurate
**Depends on**: Phase 3
**Requirements**: OPS-01, OPS-02, OPS-03
**Gap Closure:** Closes tech debt from v1.0 audit
**Success Criteria** (what must be TRUE):
  1. harvest_insights.py is triggered automatically after arena runs complete (cron, heartbeat, or Prefect flow)
  2. REQUIREMENTS.md traceability table shows correct statuses matching checkbox state
  3. NAME-01 checkbox is marked complete in traceability table
**Plans**: TBD

Plans:
- [ ] 05-01: TBD
- [ ] 05-02: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Trigger + Naming | 2/2 | Complete | 2026-03-31 |
| 2. Arena Skill | 2/2 | Complete | 2026-04-01 |
| 3. Insight Harvester | 2/2 | Complete | 2026-04-01 |
| 4. Arena Provisioning | 0/2 | Not started | - |
| 5. Ops Polish | 0/2 | Not started | - |
