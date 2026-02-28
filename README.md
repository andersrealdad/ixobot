# IXO-Synth

> Lightweight AI agent framework. Build personal assistants that talk, remember, and act.

Built on [nanobot](https://github.com/HKUDS/nanobot) by HKUDS.

## Quick Start

```bash
pip install -e .
nanobot onboard
nanobot agent -m "hello"
```

## What This Does

IXO-Synth is a fork of nanobot — an ultra-lightweight AI agent framework (~3,400 lines of core code). It connects to any LLM provider, runs tools, remembers context across sessions, and talks to users through chat channels. This fork adds Nextcloud Talk integration, QMD hybrid knowledge search, and named agent profiles.

## Architecture

<p align="center">
  <img src="nanobot_arch.png" alt="Architecture" width="800">
</p>

| Component | Purpose |
|-----------|---------|
| Agent Loop | LLM reasoning cycle with tool execution (`agent/loop.py`) |
| Tools | File ops, shell, web search/fetch, messaging, cron, spawn, QMD search |
| Channels | Telegram, Discord, WhatsApp, Feishu, Nextcloud Talk, CLI |
| Memory | Long-term `MEMORY.md` + daily notes + session history |
| Skills | Markdown-defined capabilities loaded on demand |
| Providers | Multi-provider LLM access via litellm |
| Bus | Async message queue decoupling channels from agent |
| Cron | Persistent scheduled tasks with cron expressions |
| Heartbeat | Periodic wake-up service reading `HEARTBEAT.md` |

## Channels

| Channel | Transport | Setup |
|---------|-----------|-------|
| Telegram | Long polling | Token from BotFather |
| Discord | Gateway WebSocket | Bot token + intents |
| WhatsApp | Node.js bridge (baileys) | QR code scan |
| Feishu | WebSocket long connection | App credentials |
| Nextcloud Talk | Webhook HTTP server | Bot secret + HMAC |
| CLI | Direct stdin/stdout | None |

<details>
<summary><b>Telegram</b></summary>

1. Create a bot via `@BotFather` on Telegram, copy the token.
2. Get your user ID from `@userinfobot`.
3. Configure:

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

4. Run `nanobot gateway`.

</details>

<details>
<summary><b>Discord</b></summary>

1. Create an application at https://discord.com/developers/applications.
2. Create a bot, copy the token. Enable **MESSAGE CONTENT INTENT**.
3. Get your User ID (Developer Mode > right-click avatar > Copy User ID).
4. Configure:

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["YOUR_USER_ID"]
    }
  }
}
```

5. Invite the bot via OAuth2 URL Generator (scopes: `bot`, permissions: Send Messages, Read Message History).
6. Run `nanobot gateway`.

</details>

<details>
<summary><b>WhatsApp</b></summary>

Requires Node.js 18 or later.

1. Link device: `nanobot channels login` (scan QR with WhatsApp).
2. Configure:

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+1234567890"]
    }
  }
}
```

3. Run `nanobot channels login` in one terminal, `nanobot gateway` in another.

</details>

<details>
<summary><b>Feishu</b></summary>

Uses WebSocket — no public IP required.

1. Create an app on [Feishu Open Platform](https://open.feishu.cn/app).
2. Enable Bot capability. Add `im:message` permission and `im.message.receive_v1` event (Long Connection mode).
3. Configure:

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "allowFrom": []
    }
  }
}
```

4. Run `nanobot gateway`.

</details>

<details>
<summary><b>Nextcloud Talk</b></summary>

Receives webhook POSTs from Nextcloud Talk with HMAC-SHA256 verification.

1. Register a bot in Nextcloud Talk admin settings. Copy the bot secret.
2. Configure:

```json
{
  "channels": {
    "nextcloudTalk": {
      "enabled": true,
      "serverUrl": "https://your-nextcloud.example.com",
      "botSecret": "YOUR_BOT_SECRET",
      "port": 18793,
      "replyAs": "Assistant",
      "allowFrom": []
    }
  }
}
```

3. Run `nanobot gateway`. The webhook server starts on the configured port.

</details>

## Tools

| Tool | Purpose |
|------|---------|
| `read_file` | Read file contents |
| `write_file` | Write content to a file |
| `edit_file` | Replace text in a file (exact match) |
| `list_dir` | List directory contents |
| `exec` | Execute shell commands (with safety guards) |
| `web_search` | Brave Search API (title, URL, snippet) |
| `web_fetch` | Fetch URL and extract readable content |
| `message` | Send message to a specific channel and chat |
| `spawn` | Launch a background subagent task |
| `cron` | Schedule, list, and remove recurring jobs |
| `qmd_search` | Hybrid BM25 + vector knowledge search via QMD |

## Skills

Skills are markdown files (`SKILL.md`) with YAML frontmatter. The agent discovers them from the workspace `skills/` directory (user-defined, highest priority) and the bundled `nanobot/skills/` directory (fallback). Skills with unmet requirements are filtered automatically.

The agent context always includes a compact skills summary. Full skill content is loaded on demand when the agent reads the file.

| Skill | Description | Requires |
|-------|-------------|----------|
| `cron` | Schedule reminders and recurring tasks | — |
| `github` | Interact with GitHub (PRs, issues, CI) | `gh` |
| `summarize` | Summarize URLs, podcasts, YouTube videos | `summarize` |
| `tmux` | Remote-control tmux sessions | `tmux` |
| `weather` | Weather via wttr.in and Open-Meteo | `curl` |
| `skill-creator` | Guide for creating new skills | — |

## Memory

The agent maintains two layers of persistent memory in the workspace:

- **`memory/MEMORY.md`** — long-term memory, read and written by the agent
- **`memory/YYYY-MM-DD.md`** — daily notes, appended throughout the day

Both are injected into the system prompt automatically. Session history is stored separately as JSONL files (up to 50 messages in context).

The **QMD search tool** extends memory with a knowledge base: fast BM25 keyword search (~30 ms) or deep hybrid search with vector similarity and LLM reranking (~10 s).

## Configuration

Config file: `~/.nanobot/config.json`

Minimal example:

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  },
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    }
  }
}
```

### Named Agent Profiles

Define multiple agent profiles with separate workspaces and model overrides:

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5"
    },
    "profiles": {
      "researcher": {
        "workspace": "~/.nanobot-researcher/workspace"
      },
      "coder": {
        "workspace": "~/.nanobot-coder/workspace",
        "model": "anthropic/claude-sonnet-4-5"
      }
    }
  }
}
```

Run a named profile: `nanobot agent researcher -m "search for..."`.

### Providers

| Provider | Purpose | API Key |
|----------|---------|---------|
| `openrouter` | Multi-model access (recommended) | [openrouter.ai](https://openrouter.ai) |
| `anthropic` | Claude direct | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | GPT direct | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | DeepSeek direct | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + voice transcription (Whisper) | [console.groq.com](https://console.groq.com) |
| `gemini` | Gemini direct | [aistudio.google.com](https://aistudio.google.com) |
| `vllm` | Local models (OpenAI-compatible) | Any non-empty string |
| `moonshot` | Moonshot/Kimi | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `zhipu` | ZhipuAI | [open.bigmodel.cn](https://open.bigmodel.cn) |

### Security

| Option | Default | Description |
|--------|---------|-------------|
| `tools.restrictToWorkspace` | `false` | Sandbox all file/shell tools to the workspace directory |
| `channels.*.allowFrom` | `[]` (allow all) | Allowlist of user IDs per channel |

## CLI Reference

| Command | Description |
|---------|-------------|
| `nanobot onboard` | Initialize config and workspace |
| `nanobot agent -m "..."` | Single message to the agent |
| `nanobot agent` | Interactive chat mode |
| `nanobot agent NAME -m "..."` | Chat with a named agent profile |
| `nanobot gateway` | Start all channels + agent loop |
| `nanobot status` | Show config, model, API key status |
| `nanobot channels status` | Show channel configuration |
| `nanobot channels login` | Link WhatsApp device (QR scan) |
| `nanobot cron list` | List scheduled jobs |
| `nanobot cron add --name N --message M --cron "..."` | Schedule a job |
| `nanobot cron remove JOB_ID` | Remove a job |
| `nanobot cron enable JOB_ID` | Enable/disable a job |
| `nanobot cron run JOB_ID` | Manually execute a job |

## Docker

```bash
# Build
docker build -t nanobot .

# Initialize (first time)
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# Edit config on host
vim ~/.nanobot/config.json

# Run gateway
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# Single command
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "hello"
```

The `-v` flag persists config and workspace across container restarts.

## Project Structure

```
nanobot/
├── agent/
│   ├── loop.py          # Agent loop (LLM + tool execution cycle)
│   ├── context.py       # System prompt assembly
│   ├── memory.py        # MEMORY.md + daily notes
│   ├── skills.py        # Skill discovery and loading
│   ├── subagent.py      # Background task execution
│   └── tools/
│       ├── base.py      # Tool ABC + JSON schema validation
│       ├── registry.py  # Dynamic tool registration
│       ├── filesystem.py # read_file, write_file, edit_file, list_dir
│       ├── shell.py     # exec (with deny-list safety)
│       ├── web.py       # web_search (Brave), web_fetch (Readability)
│       ├── message.py   # message (cross-channel send)
│       ├── spawn.py     # spawn (subagent launcher)
│       ├── cron.py      # cron (scheduled tasks)
│       └── qmd.py       # qmd_search (hybrid knowledge search)
├── skills/              # Bundled skills (cron, github, weather, tmux, ...)
├── channels/
│   ├── base.py          # BaseChannel ABC
│   ├── manager.py       # Channel lifecycle and dispatch
│   ├── telegram.py      # Telegram (long polling)
│   ├── discord.py       # Discord (Gateway WebSocket)
│   ├── whatsapp.py      # WhatsApp (Node.js bridge)
│   ├── feishu.py        # Feishu (WebSocket)
│   └── nextcloud_talk.py # Nextcloud Talk (webhook + HMAC)
├── bus/                 # Async message queue
├── cron/                # Job scheduling and persistence
├── heartbeat/           # Periodic wake-up service
├── providers/           # LLM providers via litellm
├── session/             # Conversation history (JSONL)
├── config/              # Pydantic config schema + loader
└── cli/                 # Typer CLI commands
bridge/                  # Node.js WhatsApp bridge (baileys)
workspace/               # Default workspace template
tests/                   # Unit + integration tests
```

## IXO-Synth Additions

What this fork adds over upstream nanobot:

- **Nextcloud Talk channel** — Webhook-based integration with HMAC-SHA256 verification, OpenClaw bridge support, and Bot API fallback.
- **QMD hybrid knowledge search** — BM25 keyword search and deep vector + LLM reranking via the `qmd` CLI tool.
- **Named agent profiles** — Run multiple agents with separate workspaces, models, and identities from a single installation.
- **Heartbeat service** — Periodic wake-up loop that reads `HEARTBEAT.md` for proactive tasks.

## Contributing

Issues and pull requests are welcome. The codebase is intentionally small and readable.

## License

[MIT](LICENSE)

## Acknowledgments

IXO-Synth is built on [nanobot](https://github.com/HKUDS/nanobot) by [HKUDS](https://github.com/HKUDS). The upstream project provides the core agent architecture, tool system, and channel framework that makes this possible.
