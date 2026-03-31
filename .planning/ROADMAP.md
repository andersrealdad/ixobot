# Roadmap: Arena Builder

## Overview

Turn every Build Order into a model competition. Phase 1 wires the trigger so IxoGSD pre-flight spawns arena tasks and aligns the repo naming. Phase 2 builds the nanobot skill that runs competitors in isolated sandboxes. Phase 3 collects all insights into PostgreSQL and posts comparison summaries.

## Phases

- [ ] **Phase 1: Trigger + Naming** - IxoGSD hook spawns arena tasks on BO claim; repo naming aligned
- [ ] **Phase 2: Arena Skill** - Nanobot skill runs two competitors in sandboxes via agent-gsd.sh
- [ ] **Phase 3: Insight Harvester** - Collect, store, and report insights from all builders

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
**Plans**: TBD

Plans:
- [ ] 01-01: TBD
- [ ] 01-02: TBD

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
**Plans**: TBD

Plans:
- [ ] 02-01: TBD
- [ ] 02-02: TBD

### Phase 3: Insight Harvester
**Goal**: All builder insights are collected, stored in PostgreSQL, and summarized for human review
**Depends on**: Phase 2
**Requirements**: HARV-01, HARV-02, HARV-03, HARV-04
**Success Criteria** (what must be TRUE):
  1. After all competitors finish a BO, their insights.jsonl files are collected into a single dataset
  2. Insights are stored in `ixonaut.arena_build_insights` table on stacks:5432
  3. Each row includes bo_id, model, insight_type, text, edges, severity, timestamp, builder_identity
  4. A summary message comparing per-model insights is posted to message_bus channel `arena-build`
**Plans**: TBD

Plans:
- [ ] 03-01: TBD
- [ ] 03-02: TBD

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Trigger + Naming | 0/2 | Not started | - |
| 2. Arena Skill | 0/2 | Not started | - |
| 3. Insight Harvester | 0/2 | Not started | - |
