# Milestones

## v1.0 Arena Builder (Shipped: 2026-04-01)

**Phases completed:** 5 phases, 9 plans, 16 tasks

**Key accomplishments:**

- Self-contained arena_trigger.py inserting 2 competitor task_queue rows (qwen3-32b + qwen3-8b) per BO claim, wired into preflight.sh as non-blocking background call
- Nanobot arena-builder skill with SKILL.md agent instructions and stdlib-only arena_run.py for sandbox execution, insights collection, and message_bus reporting
- Dry-run mode for arena_run.py with verified message_bus posting for all three result statuses (completed/flagged/error)
- PostgreSQL migration for ixonaut.arena_build_insights table and stdlib-only harvest_insights.py that detects completed BOs from message_bus and bulk-inserts insights.jsonl data via psql over ssh
- Per-model comparison summary posting to message_bus after harvest, with type/severity breakdowns and delta between competing models
- Nanobot runtime configs and identity directories for arena-competitor-a (qwen3-32b) and arena-competitor-b (qwen3-8b) via CLIProxy
- Parameterized SQL escaping in harvest_insights.py via _sql_escape() and _sql_escape_identifier() helpers replacing f-string interpolation
- Auto-trigger harvester after both arena competitors finish via message_bus count check, plus full traceability table correction

---
