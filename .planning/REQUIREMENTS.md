# Requirements: Arena Builder

**Defined:** 2026-03-31
**Core Value:** Every BO Claude Code builds also produces a training dataset from competing models

## v1 Requirements

### Trigger

- [x] **TRIG-01**: When IxoGSD pre-flight claims a BO, a task is created in task_queue targeting arena competitors
- [x] **TRIG-02**: Task includes BO ID, stripped instruks (same as Octopus), and model assignments
- [x] **TRIG-03**: Trigger is non-blocking — Claude Code continues building without waiting

### Skill

- [x] **SKIL-01**: Nanobot skill `arena-builder` exists at `nanobot/skills/arena-builder/SKILL.md`
- [x] **SKIL-02**: Skill creates isolated sandbox per competitor in `~/shared-data/DEV/garage/workshop/arena-{bo_id}-{model}/`
- [x] **SKIL-03**: Skill runs `agent-gsd.sh` with model override (`OCTOPUS_MODEL=qwen3-32b` or `qwen3-8b`)
- [x] **SKIL-04**: Skill writes `insights.jsonl` in standardized format per competitor
- [x] **SKIL-05**: Skill captures result (completed/flagged/error) and posts to message_bus

### Harvester

- [x] **HARV-01**: After all competitors finish, insights from all builders are collected
- [x] **HARV-02**: Insights stored in PostgreSQL `ixonaut.arena_build_insights` table
- [x] **HARV-03**: Table includes: bo_id, model, insight_type, text, edges, severity, timestamp, builder_identity
- [x] **HARV-04**: Summary posted to message_bus channel `arena-build` with per-model comparison

### Naming

- [x] **NAME-01**: Rename local directory or git remote to align `ixobot` (GitHub) with local workspace

### Provisioning (Gap Closure)

- [x] **PROV-01**: Agent runtime config exists at `~/agents/arena-competitor-a/config.json` and `~/agents/arena-competitor-b/config.json`
- [x] **PROV-02**: Agent identity directories exist at `~/DEV/operations/agent-homes/arena-competitor-a/` and `arena-competitor-b/`
- [x] **PROV-03**: harvest_insights.py uses parameterized SQL — no string interpolation of untrusted values

### Ops (Gap Closure)

- [ ] **OPS-01**: harvest_insights.py is triggered automatically after arena runs complete
- [ ] **OPS-02**: REQUIREMENTS.md traceability table matches checkbox state
- [ ] **OPS-03**: NAME-01 marked complete in traceability table

## v2 Requirements

### Scoring

- **SCOR-01**: Automated diff scoring between competitor outputs and Claude Code output
- **SCOR-02**: ELO-style ranking of models across multiple BOs
- **SCOR-03**: Insight quality scoring (useful vs noise)

### Training Pipeline

- **TRAIN-01**: Export arena_build_insights to JSONL format for Qwen fine-tuning
- **TRAIN-02**: Automated training trigger when dataset reaches threshold (e.g., 100 BOs)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Fine-tuning execution | Dataset collection only, training is separate infrastructure |
| GPU scheduling | Use existing gateway routing, no custom scheduler |
| Real-time streaming of competitor progress | Async results sufficient for v1 |
| Winner auto-selection | Human reviews, Arena scoring deferred to v2 |

## Traceability

| Requirement | Description | Phase | Status |
|-------------|-------------|-------|--------|
| TRIG-01 | Task created in task_queue on BO claim | Phase 1 | Complete |
| TRIG-02 | Task includes BO ID, stripped instruks, model assignments | Phase 1 | Complete |
| TRIG-03 | Trigger is non-blocking — Claude Code continues | Phase 1 | Complete |
| SKIL-01 | Nanobot skill `arena-builder` with SKILL.md | Phase 2 | Complete |
| SKIL-02 | Isolated sandbox per competitor | Phase 2 | Complete |
| SKIL-03 | Runs agent-gsd.sh with OCTOPUS_MODEL override | Phase 2 | Complete |
| SKIL-04 | Writes insights.jsonl (type, text, edges, severity) | Phase 2 | Complete |
| SKIL-05 | Posts result status to message_bus | Phase 2 | Complete |
| HARV-01 | Collect insights from all builders after completion | Phase 3 | Complete |
| HARV-02 | Store insights in PostgreSQL arena_build_insights | Phase 3 | Complete |
| HARV-03 | Table: bo_id, model, type, text, edges, severity, timestamp | Phase 3 | Complete |
| HARV-04 | Summary posted to message_bus with per-model comparison | Phase 3 | Complete |
| NAME-01 | Align local dir / git remote naming to ixobot | Phase 1 | Complete |
| PROV-01 | Agent runtime configs for arena-competitor-a/b | Phase 4 | Pending |
| PROV-02 | Agent identity directories for competitor agents | Phase 4 | Pending |
| PROV-03 | Parameterized SQL in harvest_insights.py | Phase 4 | Pending |
| OPS-01 | Automated trigger for harvest_insights.py | Phase 5 | Pending |
| OPS-02 | Traceability table matches checkbox state | Phase 5 | Pending |
| OPS-03 | NAME-01 marked complete in traceability | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 13 total (all complete)
- Gap closure requirements: 6 total (pending)
- Mapped to phases: 19
- Unmapped: 0

---
*Requirements defined: 2026-03-31*
*Last updated: 2026-04-01 after gap closure planning*
