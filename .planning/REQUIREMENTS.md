# Requirements: Arena Builder

**Defined:** 2026-03-31
**Core Value:** Every BO Claude Code builds also produces a training dataset from competing models

## v1 Requirements

### Trigger

- [x] **TRIG-01**: When IxoGSD pre-flight claims a BO, a task is created in task_queue targeting arena competitors
- [x] **TRIG-02**: Task includes BO ID, stripped instruks (same as Octopus), and model assignments
- [x] **TRIG-03**: Trigger is non-blocking — Claude Code continues building without waiting

### Skill

- [ ] **SKIL-01**: Nanobot skill `arena-builder` exists at `nanobot/skills/arena-builder/SKILL.md`
- [ ] **SKIL-02**: Skill creates isolated sandbox per competitor in `~/shared-data/DEV/garage/workshop/arena-{bo_id}-{model}/`
- [ ] **SKIL-03**: Skill runs `agent-gsd.sh` with model override (`OCTOPUS_MODEL=qwen3-32b` or `qwen3-8b`)
- [ ] **SKIL-04**: Skill writes `insights.jsonl` in standardized format per competitor
- [ ] **SKIL-05**: Skill captures result (completed/flagged/error) and posts to message_bus

### Harvester

- [ ] **HARV-01**: After all competitors finish, insights from all builders are collected
- [ ] **HARV-02**: Insights stored in PostgreSQL `ixonaut.arena_build_insights` table
- [ ] **HARV-03**: Table includes: bo_id, model, insight_type, text, edges, severity, timestamp, builder_identity
- [ ] **HARV-04**: Summary posted to message_bus channel `arena-build` with per-model comparison

### Naming

- [ ] **NAME-01**: Rename local directory or git remote to align `ixobot` (GitHub) with local workspace

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

| Requirement | Phase | Status |
|-------------|-------|--------|
| TRIG-01 | Phase 1 | Complete |
| TRIG-02 | Phase 1 | Complete |
| TRIG-03 | Phase 1 | Complete |
| SKIL-01 | Phase 2 | Pending |
| SKIL-02 | Phase 2 | Pending |
| SKIL-03 | Phase 2 | Pending |
| SKIL-04 | Phase 2 | Pending |
| SKIL-05 | Phase 2 | Pending |
| HARV-01 | Phase 3 | Pending |
| HARV-02 | Phase 3 | Pending |
| HARV-03 | Phase 3 | Pending |
| HARV-04 | Phase 3 | Pending |
| NAME-01 | Phase 1 | Pending |

**Coverage:**
- v1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0

---
*Requirements defined: 2026-03-31*
*Last updated: 2026-03-31 after initial definition*
