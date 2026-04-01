# Phase 4: Arena Provisioning - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning
**Source:** Infrastructure phase — smart discuss (minimal context)

<domain>
## Phase Boundary

Create nanobot agent runtime configs and identities for arena-competitor-a and arena-competitor-b so the heartbeat can pick up task_queue entries. Fix SQL injection in harvest_insights.py.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — pure infrastructure phase.

Key patterns from existing agents:
- Runtime config: `~/agents/{name}/config.json` (Pydantic strict, no extra fields)
- Identity: `~/DEV/operations/agent-homes/{name}/` with SOUL.md, MEMORY.md
- Reference: dario agent as template (`~/agents/dario/config.json`)
- Model: competitors use CLIProxy at localhost:8317 with openai provider
- SQL fix: use parameterized queries or proper escaping for all interpolated values in harvest_insights.py

</decisions>

<canonical_refs>
## Canonical References

### Agent Config Pattern
- `~/agents/dario/config.json` — Reference runtime config (Pydantic strict schema)
- `~/DEV/operations/agent-homes/dario/` — Reference agent identity directory

### Code to Fix
- `nanobot/skills/arena-builder/scripts/harvest_insights.py` — SQL injection at insert_insights()

### Config Schema
- `nanobot/config/schema.py` — Pydantic models for config validation

</canonical_refs>

<specifics>
## Specific Ideas

No specific requirements — infrastructure phase

</specifics>

<deferred>
## Deferred Ideas

None

</deferred>

---

*Phase: 04-arena-provisioning*
*Context gathered: 2026-04-01 via smart discuss (infrastructure phase)*
