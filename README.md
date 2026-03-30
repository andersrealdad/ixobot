# IxoBot

AI agent with persistent memory. Built on the [nanobot](https://github.com/HKUDS/nanobot) framework.

IxoBot is the **chat interface layer** of the brandfungi/IxoSynth ecosystem. It runs a fleet of named agent personas (astrid, dario, librarian, robocop, and others), each with persistent memory, a heartbeat loop, and access to a shared coordination bus. Agents communicate via Matrix rooms, Nextcloud Talk, Telegram, or HTTP — and coordinate asynchronously via SQLite queues and discussion protocols.

**Status:** Production — actively running on `superstation`. Branch: `Ixo-nanobot`.

---

## Architecture & Execution Flow

![Architecture Overview](https://excalidraw.com/#json=fqMjtzZmhSyg8WtowsRZG,NndC2K95v1KdCIfQ8R9oTg)

The system has three concurrent layers:

**1. Channel → Bus → Agent Loop**
A message arrives on any channel (Matrix, Nextcloud Talk, Telegram, HTTP, Discord, Feishu). The channel pushes an `InboundMessage` onto the async `MessageBus` queue. The `AgentLoop` dequeues it, builds context via `ContextBuilder` (identity + memory + skills), calls the LLM, executes any tool calls in a loop (max 20 iterations), and publishes the `OutboundMessage` back through the bus to the originating channel.

**2. Heartbeat Service (30-min tick)**
Each agent runs an independent `HeartbeatService`. Every tick it checks four sources:
- `HEARTBEAT.md` in the agent workspace (manual override tasks)
- `task_queue` in `shared-memory.db` (automated pipeline tasks, priority-ordered)
- `message_bus` in `shared-memory.db` (unread inter-agent messages)
- `discussions` table (open deliberations needing this agent's expertise)

If any source has work, the agent is activated and the result is written back. Agent liveness is tracked in `agent_heartbeat`.

**3. Vault Engine (Jimmy)**
A separate long-running pipeline: `VaultWatcher → Compressor → Router`.
- **VaultWatcher** polls `shared-memory.db`, all `agent-homes/*/memory/MEMORY.md` files, and Gitea repo events (every 30s / 60s / 300s respectively)
- **Compressor** uses an LLM to structure raw observations into `StructuredMemory` objects
- **Router** writes structured memories to PostgreSQL (`astrid_memory` on `stacks:5432`)

---

## Agentic Flow

![Agentic Flow & Memory Pipeline](https://excalidraw.com/#json=2apOyQTgAeDa2hEJ8BfGU,44yYRuZDhu432OOIcnWCTQ)

### Active Agents

| Agent | Role | Channel | Expertise |
|-------|------|---------|-----------|
| **astrid** | Sidekick — context, coordination | Matrix, Nextcloud Talk | coordination, orchestration |
| **dario** | Builder — implements build orders | Gitea, Matrix | implementation, feasibility |
| **librarian** | Archivist — harvests logs, synthesizes discussions | Matrix | memory, documentation |
| **robocop** | Enforcer — policy, PR review | Matrix | security, compliance |
| **overseer** | Supervisor — agent health | Matrix | quality, review |
| **archaeologist** | Gap finder — missing docs, todos | Matrix | provenance, schema |
| **agent-k / agent-smith** | Special ops | Matrix | pipeline, remediation |
| **luise / michael** | Kitchen Table perspectives | Matrix | general, business |
| **cartographer** | System topology | Matrix | dependency graphs |

### Discussion Protocol

When a task triggers deliberation, the discussion protocol activates:
1. An entry is created in `discussions` table
2. Each agent reads open discussions on heartbeat, contributes based on `AGENT_EXPERTISE` mapping
3. After `MIN_COMMENTS_FOR_PROPOSAL` (2) unique agents comment, **librarian** synthesizes a proposal
4. Proposal is written to `discussions.proposal`, status → `proposed`
5. Anders approves or rejects

Each comment includes a structured `flags` block with severity (`--flag` / `--flagpole` / `--otto`) and affected build order IDs.

### Memory Pipeline (IxoBot layer)

```
Observe (VaultWatcher) → Compress (LLM) → Store (SQLite/PG) → Reflect (crystal) → Recall (context inject)
```

- **Store:** `SqliteMemoryStore` (`~/.ixobot/memory.db`) by default; `PostgreSQLMemoryStore` optional via `brain` extras
- **Crystals:** high-importance memories promoted via `promote()`, surfaced in every future session
- **Decay:** `decay(rate=0.01)` reduces unpromoted memory scores over time
- **Recall:** crystals + recent memories injected into system prompt by `ContextBuilder`

### Trust Boundaries

| Resource | Access |
|----------|--------|
| `predictions.db` | **Read-only** — never write |
| `workflows.py` | **RFC only** — create Gitea issue, never edit directly |
| Prefect processes | **No kill** — diagnose only |
| `shared-memory.db` | Read + Write (task_queue, message_bus, discussions) |
| `astrid_memory` PostgreSQL | Write via vault engine router |

---

## Environment & Dependencies

**Languages:** Python 3.11+ (nanobot/ixobot), TypeScript (bridge/)

**Python dependencies** (`pyproject.toml`):
- `litellm` — multi-provider LLM abstraction (OpenAI, Anthropic, Groq, vLLM, Ollama)
- `pydantic` / `pydantic-settings` — config schema + validation
- `loguru` — structured logging
- `typer` + `rich` — CLI
- `httpx` / `websockets` / `websocket-client` — HTTP + WS channels
- `croniter` — cron job scheduling
- `python-telegram-bot` — Telegram channel
- `lark-oapi` — Feishu channel
- `matrix-nio[e2e]` — Matrix channel with E2E encryption (optional extra)
- `psycopg2-binary` + `pgvector` — PostgreSQL memory backend (optional `brain` extra)

**System services:**
| Service | Host | Port | Purpose |
|---------|------|------|---------|
| CLIProxyAPI | `superstation` | 8317 | Claude MAX as OpenAI-compatible API (zero cost) |
| Ollama | `superstation` | 11434 | Local LLMs (Qwen3-8B Technician, Llama) |
| PostgreSQL | `stacks` | 5432 | Vault engine memory store (`astrid_memory`) |
| Matrix (Conduit) | `superstation` | 8448 | Agent ↔ agent + human chat |
| Gitea | `ubsfuru` | 3001 | Repo notifications (VaultWatcher) |
| shared-memory.db | `superstation` | — | `~/shared-data/db/shared-memory.db` (SQLite) |
| PGX SGLang | `pgx-trd` | — | Pending BO#060 — Blackwell inference server |

**Hardware:** RX 7900 XTX (24GB VRAM) on `superstation` for Ollama. Blackwell GB10 (128GB) coming via BO#060.

---

## Component Specification

```
ixobot/
├── nanobot/                    # Open-source agent framework
│   ├── __main__.py             # Entry point: python -m nanobot → CLI app
│   ├── cli/commands.py         # Typer app: agent, gateway, onboard, status
│   ├── agent/
│   │   ├── loop.py             # AgentLoop: dequeue → context → LLM → tools → respond
│   │   ├── context.py          # ContextBuilder: assembles system prompt (SOUL+MEMORY+skills)
│   │   ├── memory.py           # MEMORY.md + daily notes read/write
│   │   ├── skills.py           # Discovers SKILL.md files, progressive disclosure
│   │   ├── subagent.py         # SubagentManager: background task execution
│   │   └── tools/
│   │       ├── base.py         # Tool ABC: name, description, parameters, execute()
│   │       ├── registry.py     # Dynamic registration + dispatch
│   │       ├── filesystem.py   # ReadFile, WriteFile, EditFile, ListDir
│   │       ├── shell.py        # ExecTool: shell commands (sandboxable)
│   │       ├── web.py          # WebSearch (Brave API), WebFetch
│   │       ├── message.py      # MessageTool: send to channel
│   │       ├── spawn.py        # SpawnTool: launch subagents
│   │       ├── cron.py         # CronTool: schedule future tasks
│   │       ├── flash.py        # Flash tool: Matrix message editing
│   │       └── qmd.py          # QmdSearchTool: hybrid knowledge graph search
│   ├── channels/
│   │   ├── base.py             # BaseChannel ABC: start(), stop(), send()
│   │   ├── manager.py          # ChannelManager: init, start, stop, dispatch
│   │   ├── matrix.py           # Matrix via nio: E2E, threading, room-per-chat_id
│   │   ├── nextcloud_talk.py   # Nextcloud Talk webhook (IxoSynth addition)
│   │   ├── telegram.py         # python-telegram-bot
│   │   ├── discord.py          # discord.py
│   │   ├── feishu.py           # Lark/Feishu via lark-oapi
│   │   ├── http_inbound.py     # HTTP POST endpoint (nanobot gateway)
│   │   └── whatsapp.py         # WhatsApp via bridge/
│   ├── heartbeat/
│   │   ├── service.py          # HeartbeatService: 4-source tick loop, discussion protocol
│   │   └── open_brain.py       # Open Brain MCP: capture/search semantic memories
│   ├── vault/
│   │   ├── engine.py           # Jimmy: Watcher→Compressor→Router pipeline entry point
│   │   ├── watcher.py          # VaultWatcher: polls SQLite, MEMORY.md files, Gitea API
│   │   ├── compressor.py       # Compressor: LLM structures raw observations
│   │   ├── router.py           # Router: writes StructuredMemory to PostgreSQL
│   │   ├── reflection.py       # Promote + decay + resurrection logic
│   │   └── config.py           # Vault engine config
│   ├── mcp/
│   │   ├── client.py           # McpClientManager: connects to MCP SSE servers
│   │   ├── bridge.py           # register_mcp_tools(): wraps MCP tools as nanobot Tools
│   │   └── linker.py           # Tool linking utilities
│   ├── providers/
│   │   ├── litellm_provider.py # LiteLLMProvider: multi-model, proxy_ prefix stripping
│   │   └── transcription.py    # Groq Whisper voice-to-text
│   ├── bus/
│   │   ├── queue.py            # MessageBus: asyncio.Queue wrapper
│   │   └── events.py           # InboundMessage, OutboundMessage dataclasses
│   ├── session/manager.py      # SessionManager: JSONL history per channel:chat_id
│   ├── cron/service.py         # CronService: croniter-based job scheduler
│   ├── config/
│   │   ├── schema.py           # Pydantic Config root model
│   │   └── loader.py           # load_config(): path resolution, profile merge
│   └── skills/                 # Bundled skills (SKILL.md + scripts/)
│       ├── tmux/               # tmux session management
│       ├── cron/               # Cron scheduling skill
│       ├── weather/            # Weather lookup
│       ├── github/             # GitHub integration
│       ├── gitea-lookup/       # Gitea issue/PR lookup (scripts/gitea.py)
│       ├── gsd-config/         # GSD build order workflow config
│       └── skill-creator/      # Meta-skill for creating new skills
├── ixobot/                     # Proprietary product layer
│   └── memory/
│       ├── store.py            # PersistentMemoryStore ABC: store, query, promote, get_crystals, decay
│       ├── sqlite_store.py     # SqliteMemoryStore: zero-config default (~/.ixobot/memory.db)
│       ├── context.py          # Memory context injection into agent system prompt
│       └── schema.sql          # SQLite schema: memories, crystals tables
├── bridge/                     # WhatsApp bridge (Node.js/TypeScript)
│   └── src/
│       ├── index.ts            # Entry point
│       ├── server.ts           # Express server
│       └── whatsapp.ts         # whatsapp-web.js integration
├── gsd/                        # IxoGSD build order workflow
│   ├── manage.sh               # Kanban manager: status, board, promote
│   └── templates/TEMPLATE.md   # Build order template
├── workspace/                  # Default agent identity (used if no agent-home override)
│   ├── SOUL.md                 # Personality: helpful, concise, accurate
│   ├── TOOLS.md                # Tool capabilities reference
│   ├── USER.md                 # User context
│   ├── AGENTS.md               # Agent roster
│   ├── HEARTBEAT.md            # Task override file
│   └── memory/MEMORY.md        # Agent memory (hot layer)
├── Dockerfile                  # Multi-stage: python:3.12-slim, installs nanobot
├── pyproject.toml              # Package: ixobot v1.0.0, scripts: nanobot + ixobot
└── SECURITY.md                 # Responsible disclosure policy
```

### Key Config Schema

```
Config
├── agents.defaults.model           # Default LLM model string (litellm format)
├── agents.defaults.workspace       # Default workspace path
├── agents.profiles                 # Named profiles: workspace + model override
├── channels.matrix                 # homeserver, user_id, access_token, default_room
├── channels.nextcloud_talk         # url, username, password, room_token
├── channels.telegram               # bot_token
├── channels.discord                # bot_token
├── channels.feishu                 # app_id, app_secret, verification_token
├── providers.openai/anthropic/...  # api_key, api_base (use CLIProxy: http://superstation:8317/v1)
├── gateway.host/port               # Gateway bind (default 0.0.0.0:18790)
├── tools.web.search.apiKey         # Brave Search API key
├── tools.exec.timeout              # Shell timeout seconds (default 60)
├── tools.restrictToWorkspace       # Sandbox mode
└── logging.level                   # Default WARNING
```

Config file: `~/.nanobot/config.json` (or `~/.nanobot-<profile>/config.json` for named profiles).
Runtime agent configs: `~/agents/<name>/config.json` — uses `${VAULT:secret-name}` placeholders resolved by `start-agent.sh`.

---

## Data & State

### Databases

| Database | Host | Schema | Tables | Access |
|----------|------|--------|--------|--------|
| `astrid_memory` | `stacks:5432` | `public` | `astrid_events`, `embeddings`, `task_log`, `agent_heartbeat` | Read+Write |
| `astrid_memory` | `stacks:5432` | `ixonaut` | `predictions_full`, `reasoning_chains`, `knowledge_embeddings` | Read+Write (vault engine) |
| `shared-memory.db` | `superstation` | — | `task_queue`, `message_bus`, `discussions`, `discussion_comments`, `agent_heartbeat`, `debate_utxo`, `memo_inbox` | Read+Write |
| `~/.ixobot/memory.db` | per-agent | — | `memories`, `crystals` | Read+Write |

### SQLite Tables in shared-memory.db

- **`task_queue`** — tasks dispatched to specific agents. Priorities: `p0-critical`, `p1-high`, `p2-medium`, `p3-low`. States: `pending → claimed → done/failed`
- **`message_bus`** — inter-agent messages. `read_by` is a JSON array of agent names who have read it. Wildcard `to_agent='*'` broadcasts to all
- **`agent_heartbeat`** — liveness tracking. `agent_type` distinguishes `nanobot` vs `claude-code` vs `service` (vault-watcher). Claude Code sessions auto-pruned after 24h
- **`discussions`** — deliberation threads. States: `open → discussing → proposed → approved/rejected`
- **`discussion_comments`** — per-agent contributions with role (`reviewer` / `synthesizer`) and flags block
- **`debate_utxo`** — unspent debate observations from the prediction engine

### File-based State

| Path | Purpose |
|------|---------|
| `workspace/memory/MEMORY.md` | Hot memory layer — agent writes here, injected into context |
| `workspace/HEARTBEAT.md` | Manual task override — read every heartbeat tick |
| `~/agents/<name>/config.json` | Runtime config with vault refs — NOT git-tracked |
| `~/.nanobot/cron.json` | Persisted cron jobs |
| `~/.nanobot/<profile>/sessions/<channel>/<chat_id>.jsonl` | Conversation history per channel+room |
| `~/.nanobot/matrix-store/<username>/` | Matrix E2E encryption key store |
| `~/.local/share/vault-engine/engine.log` | Vault engine log (10MB rotation, 7-day retention) |

---

## Setup & Deployment

### Fresh Install

```bash
# Clone
git clone git@github.com:andersrealdad/ixobot.git
cd ixobot
git checkout Ixo-nanobot

# Install (editable, with all extras)
uv pip install -e ".[brain,matrix,dev]"

# Verify
nanobot --help
```

### Agent Runtime (brandfungi production)

Agents run via `~/agents/start-agent.sh <name>` which:
1. Reads `~/agents/<name>/config.json`
2. Resolves `${VAULT:secret-name}` placeholders via bw-serve (`http://superstation:8087`)
3. Sets `NANOBOT_AGENT_NAME=<name>` and `NANOBOT_HEARTBEAT_INTERVAL`
4. Starts the agent process

```bash
~/agents/start-agent.sh astrid
~/agents/start-agent.sh dario
~/agents/start-agent.sh librarian
```

Agent identities (SOUL.md, TOOLS.md, MEMORY.md) live in:
```
~/DEV/operations/agent-homes/<name>/
```

### Vault Engine (Jimmy)

```bash
python -m nanobot.vault.engine
# or: vault-engine.service (systemd)
```

Requires: `NANOBOT_PG_PASSWORD` env var, or `postgres-credentials` in Bitwarden vault.

### Docker

```bash
docker build -t ixobot .
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 ixobot gateway
```

### Verify Running

```bash
# Test HTTP inbound
curl -X POST http://superstation:18790/inbound \
  -d '{"content":"ping","chat_id":"test","channel":"test"}'

# Check heartbeat in shared-memory
sqlite3 ~/shared-data/db/shared-memory.db \
  "SELECT agent_id, status, last_heartbeat FROM agent_heartbeat ORDER BY last_heartbeat DESC LIMIT 10;"
```

---

## Usage / API

### CLI

```bash
nanobot onboard                        # Initialize config + workspace
nanobot agent                          # Interactive REPL (default profile)
nanobot agent --name dario             # Named agent profile
nanobot agent -m "What do you know?"  # Single message
nanobot gateway                        # Start all channels + agent loop
nanobot status                         # Show config + API key check
```

### HTTP Inbound

```bash
POST http://superstation:18790/inbound
{
  "content": "message text",
  "chat_id": "room-id",
  "channel": "http",
  "sender_id": "user"
}
```

### IxoGSD Build Orders

```bash
cd gsd
bash manage.sh status       # View all build orders
bash manage.sh board        # Kanban view
bash manage.sh promote 042  # Advance a build order one station
```

Promotion chain: `drafted → under-review → cross-check → approved → queued → building → deployed → done/`

### Python (library use)

```python
from ixobot.memory.sqlite_store import SqliteMemoryStore

store = SqliteMemoryStore("~/.ixobot/memory.db")
mem_id = store.store({
    "content": "Anders prefers concise responses",
    "memory_type": "preference",
    "importance": 0.8,
    "agent_name": "astrid",
})
crystals = store.get_crystals(limit=5)
```

---

## Known Limitations & Experimental Quirks

- **`proxy_` prefix stripping** — `AgentLoop._normalize_tool_name()` strips `proxy_` from tool names. This is a CLIProxyAPI artifact where the proxy cloaks tool names. If CLIProxy changes this behavior, tool dispatch will silently break.
- **Discussion synthesis is librarian-only** — hardcoded: only `agent_name == "librarian"` synthesizes proposals. Other agents can contribute but never synthesize, even if librarian is offline.
- **`MIN_COMMENTS_FOR_PROPOSAL = 2`** — low threshold. A single agent commenting twice (different discussions) can trigger synthesis. In practice this works because agents don't comment on their own discussions.
- **Vault engine is read-only on sources** — `VaultWatcher` never modifies `shared-memory.db`. However, a crash mid-watermark update can cause re-processing of already-seen events on restart (no at-least-once guarantee on the watcher side).
- **Matrix E2E store** — key store lives in `~/.nanobot/matrix-store/<username>/`. Deleting this directory causes the agent to lose E2E session context and may require re-verification.
- **WhatsApp bridge** — Node.js service (`bridge/`) runs separately from the Python agent. No auto-restart or healthcheck is built in.
- **PGX SGLang (BO#060)** — listed as provider but not yet connected. Blocked on Tailscale whitelist (ITsjefen). Workaround via autossh tunnel exists but is not wired in.
- **Heartbeat interval** — default 30 minutes (`DEFAULT_HEARTBEAT_INTERVAL_S`). Configurable via `NANOBOT_HEARTBEAT_INTERVAL` env var. Very short intervals will flood the LLM backend.
- **`max_iterations = 20`** — hard cap on agent reasoning loops. Complex multi-tool tasks silently return partial results if they hit the cap. No warning is emitted to the user.
- **Memory decay** — `decay(rate=0.01)` is implemented but not wired to any scheduler. Must be called manually or via a cron task.
