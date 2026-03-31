# Arena Builder — Competitive BO Execution with Insight Harvesting

## What This Is

A nanobot skill that triggers parallel model competitions whenever Claude Code starts building a Build Order. Two nanobot agents (running different LLMs via SGLang/Ollama) attempt the same BO in isolated sandboxes simultaneously. All three builders (Claude + 2 competitors) produce structured insights that become training data for model fine-tuning.

## Core Value

Every Build Order Claude Code executes also produces a structured dataset comparing how different models approach the same problem — turning daily work into continuous model improvement.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Trigger mechanism: when IxoGSD pre-flight claims a BO, arena competitors are spawned
- [ ] Nanobot skill `arena-builder` that wraps `agent-gsd.sh` in isolated sandboxes
- [ ] Two competitor agents run same BO with different models (Qwen3-32B via SGLang, Qwen3-8B via Ollama)
- [ ] Each competitor produces `insights.jsonl` with standardized format (type, text, edges, severity)
- [ ] Insight harvester collects all three builders' insights into shared dataset
- [ ] Dataset stored in PostgreSQL (`ixonaut.arena_insights`) for fine-tuning pipeline
- [ ] Results posted to message_bus for human review
- [ ] Repo naming: align GitHub `ixobot` with local `ixosynth` directory

### Out of Scope

- Fine-tuning pipeline itself — dataset collection only, training is separate
- Changing GSD internals — arena wraps GSD, doesn't modify it
- GPU allocation optimization — models use existing gateway routing
- Automated winner selection — humans review, Arena scoring comes later

## Context

- **Nanobot framework:** `~/DEV/ixosynth/nanobot/` — agents with heartbeat, task_queue, skills
- **Agent-gsd.sh:** `~/DEV/garage/infra/octopus/agent-gsd.sh` — runs Claude CLI with GSD in devbox sandbox
- **Octopus orchestrator:** `~/DEV/garage/infra/octopus/octopus_v0.py` — Prefect flow polling buildorders/
- **AI Gateway:** LiteLLM at localhost:8300 routing to CLIProxy, Ollama, PGX SGLang
- **Build orders:** `~/DEV/garage/buildorders/` with manage.sh promotion chain
- **IxoGSD plugin:** `~/.claude/plugins/local/ixogsd/` — pre-flight/build/post-flight wrapper
- **Existing Arena:** `~/DEV/ixonaut/src/ixonaut/core/arena_runner.py` — prediction model arena (different domain but same pattern)
- **GitHub repo:** `https://github.com/andersrealdad/ixobot` — public name is ixobot

## Constraints

- **Isolation:** Competitors MUST run in isolated sandboxes (no access to each other's work)
- **Cost:** Competitors use local models (Qwen via Ollama/SGLang) — zero API cost
- **Time:** Competitors get same timeout as Octopus (30 min for GSD mode)
- **No interference:** Arena runs must not block or slow Claude Code's real build

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Use agent-gsd.sh as competitor engine | Already handles GSD in sandbox, proven | -- Pending |
| Store insights in PostgreSQL | Queryable, joins with predictions data | -- Pending |
| Trigger from IxoGSD pre-flight | Natural hook point, BO already claimed | -- Pending |
| Two competitors (not N) | Qwen3-32B + Qwen3-8B covers range | -- Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check -- still the right priority?
3. Audit Out of Scope -- reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-31 after initialization*
