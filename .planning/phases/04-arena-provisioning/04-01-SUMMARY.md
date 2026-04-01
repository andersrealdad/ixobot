---
phase: 04-arena-provisioning
plan: 01
subsystem: infra
tags: [nanobot, agent-provisioning, arena, qwen, cliproxy]

requires:
  - phase: 02-arena-skill
    provides: arena-builder skill that competitors will execute
provides:
  - Runtime configs for arena-competitor-a (qwen3-32b) and arena-competitor-b (qwen3-8b)
  - Identity directories with SOUL.md and MEMORY.md for both competitors
affects: [04-arena-provisioning, 05-ops-polish]

tech-stack:
  added: []
  patterns: [nanobot agent provisioning pattern, CLIProxy openai provider routing]

key-files:
  created:
    - ~/agents/arena-competitor-a/config.json
    - ~/agents/arena-competitor-b/config.json
    - ~/DEV/operations/agent-homes/arena-competitor-a/SOUL.md
    - ~/DEV/operations/agent-homes/arena-competitor-a/MEMORY.md
    - ~/DEV/operations/agent-homes/arena-competitor-b/SOUL.md
    - ~/DEV/operations/agent-homes/arena-competitor-b/MEMORY.md
  modified: []

key-decisions:
  - "Runtime configs use openai provider with CLIProxy at localhost:8317/v1 to route to Ollama models"
  - "Excluded tier and gitea fields from configs to match Pydantic strict schema"
  - "Minimal identity files (SOUL.md + MEMORY.md only) -- arena competitors don't need AGENTS.md/USER.md/TOOLS.md"

patterns-established:
  - "Arena agent config pattern: openai provider prefix routes through CLIProxy to local Ollama models"
  - "Arena identity pattern: minimal SOUL.md with agent name, model, sandbox path, and message_bus channel"

requirements-completed: [PROV-01, PROV-02]

duration: 2min
completed: 2026-04-01
---

# Phase 4 Plan 1: Arena Agent Provisioning Summary

**Nanobot runtime configs and identity directories for arena-competitor-a (qwen3-32b) and arena-competitor-b (qwen3-8b) via CLIProxy**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-01T01:50:21Z
- **Completed:** 2026-04-01T01:52:52Z
- **Tasks:** 2
- **Files created:** 6

## Accomplishments
- Created runtime configs for both arena competitors with correct model assignments and CLIProxy routing
- Created identity directories with SOUL.md describing each competitor's role, model, and sandbox path
- Both configs validated against Pydantic schema constraints (no extra fields beyond Config model)

## Task Commits

Task 1 (runtime configs) and Task 2 (identity files) were created and auto-synced:

1. **Task 1: Create agent runtime configs** - runtime configs at ~/agents/ (not git-tracked by design)
2. **Task 2: Create agent identity directories** - `23cbd4e` in operations repo (auto-synced)

Note: Runtime configs at ~/agents/ are intentionally not git-tracked (contains vault references). Identity files at ~/DEV/operations/agent-homes/ are git-tracked and were committed via auto-sync.

## Files Created/Modified
- `~/agents/arena-competitor-a/config.json` - Runtime config: qwen3-32b via CLIProxy, port 9891
- `~/agents/arena-competitor-b/config.json` - Runtime config: qwen3-8b via CLIProxy, port 9892
- `~/DEV/operations/agent-homes/arena-competitor-a/SOUL.md` - Identity: role, model, sandbox path
- `~/DEV/operations/agent-homes/arena-competitor-a/MEMORY.md` - Empty hot memory
- `~/DEV/operations/agent-homes/arena-competitor-b/SOUL.md` - Identity: role, model, sandbox path
- `~/DEV/operations/agent-homes/arena-competitor-b/MEMORY.md` - Empty hot memory

## Decisions Made
- Used `openai` provider key (not `claude-max`) since models are openai-prefixed (openai/qwen3-32b)
- Excluded `tier` and `gitea` fields from dario's config pattern -- not in Pydantic Config schema
- Minimal identity: SOUL.md + MEMORY.md only, no AGENTS.md/USER.md/TOOLS.md since competitors run via arena-builder skill

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all files contain real configuration and identity content.

## Next Phase Readiness
- Agent configs ready for nanobot to load via start-agent.sh
- Identity directories ready for workspace bootstrap
- Plan 04-02 (SQL injection fix) can proceed independently

## Self-Check: PASSED

All 6 created files verified present. Commit 23cbd4e verified in operations repo. SUMMARY.md exists.

---
*Phase: 04-arena-provisioning*
*Completed: 2026-04-01*
