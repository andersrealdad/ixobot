# Ship Insights — 2026-03-16 — Vault Engine Integration

## Narrative Hooks
- **"The botfarm from China that became an AI memory engine"** — nanobot is a fork of HKUDS/nanobot from Harbin Institute of Technology. Today we wired a PostgreSQL vault with graph edges into its context builder. The Chinese open-source foundation now runs a Nordic sovereign memory pipeline.
- **"Agents that remember what they learned yesterday"** — Every nanobot agent now receives vault insights in their system prompt automatically. No per-agent code changes. The memory hierarchy went from files to PostgreSQL to vector search to structured recall in one session.
- **"A daemon that watches everything"** — vault-watcher tails 7 event sources (SQLite, Gitea, file system) and normalises them into a single observation queue. Fan-in pattern, asyncio TaskGroup, 38MB memory footprint.

## Architecture Insights
```
Event Sources ──────────────────────────────────────────────┐
  message_bus (SQLite)                                      │
  task_queue (SQLite)                                       │
  debate_utxo (SQLite)                                      │
  agent_heartbeat (SQLite)          ┌──────────────────┐    │
  discussions (SQLite)        ───►  │  VaultWatcher     │ ◄──┘
  MEMORY.md (file mtime)            │  (asyncio fan-in) │
  Gitea API (closed issues)         └────────┬─────────┘
                                             │
                                    asyncio.Queue[RawObservation]
                                             │
                                             ▼
                                   [Observer/Compressor #122]
                                             │
                                             ▼
                          ┌──────────────────────────────────┐
                          │  vault.memories (PostgreSQL)       │
                          │  + vault.edges (graph)             │
                          │  + vault.checkpoints (audit)       │
                          └──────────────────────────────────┘
                                             │
                              ┌──────────────┼──────────────┐
                              ▼              ▼              ▼
                        ContextBuilder   HEARTBEAT.md   Kitchen Table
                        (system prompt)  (promoted)     (/api/vault/stats)
```

Two memory layers now coexist:
- **Open Brain** (`public.thoughts`, 384-dim MiniLM) — semantic agent knowledge
- **Vault** (`vault.memories`, 1536-dim placeholder) — structured lifecycle memory with decay, graph edges, importance scoring

Vault recall is SQL-only for now (importance + recency). Vector search deferred until embedding dimension aligned.

## Technical Decisions
- **SQL-only vault recall vs. vector search**: Chose SQL filtering (importance >= 5, agent_id match) because the embed server produces 384-dim but vault schema specifies 1536-dim. Pragmatic — works today, vector search is additive later.
- **Fan-in via asyncio.Queue, not Redis**: Chose in-process queue over Redis stream because (a) watcher is single-process, (b) Observer/Compressor (#122) will consume from same queue, (c) one less dependency. Redis can be added later as a horizontal scaling path.
- **`User=superfuru` in systemd user service**: This was the root cause of the 216/GROUP error. User services already run as the user — specifying `User=` triggers a permissions check that user-level systemd can't perform. Removed it.
- **`asyncio.get_event_loop()` → `get_running_loop()`**: Python 3.10+ deprecates `get_event_loop()` in non-main threads. The executor-based SQLite polling runs in a thread, so `get_running_loop()` is required. The loop reference is captured once in `run()` and stored as `self._loop` for thread-safe `call_soon_threadsafe()`.

## Numbers That Matter
- 6 tests passed, 0 failed
- +926 lines added, -8 removed across 7 files
- vault-watcher processes 100+ message_bus rows + 50+ task_queue entries on first poll
- 38MB memory footprint in systemd
- 13 indexes on vault schema (HNSW, GIN, partial, composite)
- 3 tables: vault.memories (168KB), vault.edges (40KB), vault.checkpoints (16KB)

## What's Next
- **#122 Observer/Compressor** — consume RawObservation from watcher queue, distill into structured vault.memories entries
- **#123 Router/Scorer** — categorise, embed (needs dimension decision: 384 vs 1536), store
- **Embedding dimension resolution** — 384 (MiniLM, localhost:8201) vs 1536 (OpenAI). Decision blocks vector search on vault.
- **#127 Reflection Loop** — Prefect flow for promote/prune/synthesize/decay
- **vault-watcher 24h stability test** — service is running, needs monitoring

## Journalist Assessment

| Question | Answer | Template |
|----------|--------|----------|
| Milestone-worthy? | Yes — first time agents have structured memory recall in system prompt | milestone-update.md |
| Has a visual? | Yes — architecture diagram, Kitchen Table /api/vault/stats | diagram-article.md |
| Architecture change? | Yes — new vault schema, new daemon service, new data flow | diagram-article.md |
| Demo-worthy? | Yes — vault-watcher live in journalctl, vault stats API | video-script.md |

---
Generated by IxoSynth Claude Code — 2026-03-16
