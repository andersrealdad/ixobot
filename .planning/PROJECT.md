# Arena Builder — Competitive BO Execution with Insight Harvesting

## What This Is

A nanobot skill that triggers parallel model competitions whenever Claude Code starts building a Build Order. Two nanobot agents (running different LLMs via Ollama/CLIProxy) attempt the same BO in isolated sandboxes simultaneously. All three builders (Claude + 2 competitors) produce structured insights that are collected into PostgreSQL for training data and human review.

## Core Value

Every Build Order Claude Code executes also produces a structured dataset comparing how different models approach the same problem — turning daily work into continuous model improvement.

## Current State

**Shipped v1.0** (2026-04-01) — 5 phases, 9 plans, 976 LOC Python + SQL.

Pipeline: `preflight.sh → arena_trigger.py → task_queue → heartbeat → arena_run.py → insights.jsonl → harvest_insights.py → PostgreSQL + message_bus summary`

All 19 requirements satisfied. Agent instances provisioned. Harvester auto-triggered.

## Requirements

### Validated

- ✓ Trigger mechanism: IxoGSD pre-flight spawns arena competitors on BO claim — v1.0
- ✓ Nanobot skill `arena-builder` wraps `agent-gsd.sh` in isolated sandboxes — v1.0
- ✓ Two competitors with different models (Qwen3-32B + Qwen3-8B) — v1.0
- ✓ Each competitor produces `insights.jsonl` (type, text, edges, severity) — v1.0
- ✓ Insight harvester collects all insights into PostgreSQL (`ixonaut.arena_build_insights`) — v1.0
- ✓ Per-model comparison summary posted to message_bus — v1.0
- ✓ Repo naming aligned: ixobot on both remotes — v1.0
- ✓ Agent runtime configs + identities for competitors — v1.0
- ✓ SQL injection fixed with safe escaping — v1.0
- ✓ Harvester auto-triggered after both competitors finish — v1.0

### Active (v2.0)

- [ ] Switch competitors to Qwen 3.5 FL4 vs Qwen 3-next-coder (generalist vs specialist)
- [ ] Automated diff scoring between competitor outputs and Claude Code output
- [ ] ELO-style ranking across multiple BOs
- [ ] Insight quality scoring (useful vs noise)
- [ ] Export arena_build_insights to JSONL for Qwen fine-tuning
- [ ] Automated training trigger at dataset threshold

### Out of Scope

- Fine-tuning execution — dataset collection only, training is separate infrastructure
- GPU scheduling — use existing gateway routing
- Real-time streaming of competitor progress — async results sufficient
- Winner auto-selection — human reviews, automated scoring deferred to v2

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use agent-gsd.sh as competitor engine | Already handles GSD in sandbox, proven | ✓ Good — works with all modes |
| Store insights in PostgreSQL | Queryable, joins with predictions data | ✓ Good — table live on stacks |
| Trigger from IxoGSD pre-flight | Natural hook point, BO already claimed | ✓ Good — non-blocking background |
| Two competitors (not N) | Qwen3-32B + Qwen3-8B covers range | ✓ Good — v2 will switch to FL4 vs next-coder |
| stdlib-only scripts | No pip deps, same pattern as arena_trigger.py | ✓ Good — zero install friction |
| psql-over-ssh for PostgreSQL | No psycopg2 needed, uses existing ssh trust | ✓ Good — works with safe escaping |
| Insights from build artifacts, not LLM memory | Qwen3-8B unreliable for self-reporting | ✓ Good — post-processes result.json/DONE.md/FLAG.md |
| Harvester auto-trigger in arena_run.py | Simpler than cron, keeps pipeline self-contained | ✓ Good — fires after both competitors done |

## Constraints

- **Isolation:** Competitors MUST run in isolated sandboxes (no access to each other's work)
- **Cost:** Competitors use local models (Qwen via Ollama) — zero API cost
- **Time:** Competitors get same timeout as Octopus (30 min for GSD mode)
- **No interference:** Arena runs must not block or slow Claude Code's real build

---
*Last updated: 2026-04-01 after v1.0 milestone*
