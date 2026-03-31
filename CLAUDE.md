# IxoSynth — Claude Code Guide

Fork of [HKUDS/nanobot](https://github.com/HKUDS/nanobot). Branch: `Ixo-nanobot`.

## Build & Run

```bash
# Install (editable)
uv pip install -e .

# Run tests
python3 -m pytest tests/test_tool_validation.py

# CLI
nanobot onboard                  # Initialize config + workspace
nanobot agent -m "test"          # Single message
nanobot agent                    # Interactive REPL
nanobot agent researcher -m "x"  # Named profile
nanobot gateway                  # Start all channels + agent loop
nanobot status                   # Config and API key check

# Docker
docker build -t nanobot .
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway
```

## Architecture

| Layer | Path | Purpose |
|-------|------|---------|
| CLI | `nanobot/cli/commands.py` | Typer app, entry point |
| Agent loop | `nanobot/agent/loop.py` | LLM reasoning + tool dispatch cycle |
| Context | `nanobot/agent/context.py` | System prompt assembly (identity + memory + skills) |
| Memory | `nanobot/agent/memory.py` | MEMORY.md + daily notes read/write |
| Skills | `nanobot/agent/skills.py` | Discovers SKILL.md files, progressive disclosure |
| Subagent | `nanobot/agent/subagent.py` | Background task execution |
| Tools | `nanobot/agent/tools/` | Each tool inherits from `base.py:Tool` |
| Tool registry | `nanobot/agent/tools/registry.py` | Dynamic registration + dispatch |
| Channels | `nanobot/channels/` | Each inherits from `base.py:BaseChannel` |
| Channel mgr | `nanobot/channels/manager.py` | Init, start, stop, dispatch |
| Bus | `nanobot/bus/queue.py` | Async message queue (channel <-> agent) |
| Config | `nanobot/config/schema.py` | Pydantic models (root: `Config`) |
| Config loader | `nanobot/config/loader.py` | `load_config()`, path resolution |
| Providers | `nanobot/providers/litellm_provider.py` | Multi-provider LLM via litellm |
| Transcription | `nanobot/providers/transcription.py` | Groq Whisper voice-to-text |
| Sessions | `nanobot/session/manager.py` | JSONL history per channel:chat_id |
| Cron | `nanobot/cron/service.py` | Job scheduling, persists to JSON |
| Heartbeat | `nanobot/heartbeat/service.py` | 30-min wake loop, reads HEARTBEAT.md |

## Conventions

- **Async throughout** — asyncio, `async def` on all tool execute methods
- **Type hints** on all functions
- **Pydantic** for config and validation (`nanobot/config/schema.py`)
- **loguru** for logging
- **Tools return strings** — not structured data
- **Config JSON uses camelCase**, Python code uses snake_case
- **Config file:** `~/.nanobot/config.json` (or `~/.nanobot-<name>/config.json` for profiles)
- **Workspace bootstrap files:** AGENTS.md, SOUL.md, USER.md, TOOLS.md, HEARTBEAT.md, memory/MEMORY.md

## Adding a Tool

1. Create `nanobot/agent/tools/your_tool.py`
2. Inherit from `Tool` (`from nanobot.agent.tools.base import Tool`)
3. Implement: `name` (str), `description` (str), `parameters` (JSON Schema dict), `async execute(self, **params) -> str`
4. Register in `loop.py:_register_default_tools()` — instantiate and call `self.tools.register(YourTool())`

See `nanobot/agent/tools/qmd.py` for a clean example.

## Adding a Channel

1. Create `nanobot/channels/your_channel.py`
2. Inherit from `BaseChannel` (`from nanobot.channels.base import BaseChannel`)
3. Implement: `async start()`, `async stop()`, `async send(OutboundMessage)`
4. Add config model in `nanobot/config/schema.py` (add to `ChannelsConfig`)
5. Register in `nanobot/channels/manager.py` — add to `_init_channels()`

See `nanobot/channels/nextcloud_talk.py` for reference.

## Adding a Skill

1. Create directory `nanobot/skills/your-skill/SKILL.md` (bundled) or `workspace/skills/your-skill/SKILL.md` (user)
2. Add YAML frontmatter: `name`, `description`, `requires` (optional list of CLI tools or env vars)
3. Write instructions in markdown body
4. Optional: add `scripts/`, `references/`, `assets/` subdirectories

## IxoSynth Additions (over upstream)

- `nanobot/channels/nextcloud_talk.py` — Nextcloud Talk webhook channel
- `nanobot/agent/tools/qmd.py` — QMD hybrid knowledge search tool
- Named agent profiles in config schema
- Heartbeat service enhancements

## Key Config Schema (Pydantic)

```
Config
├── agents.defaults.model        # Default LLM model
├── agents.defaults.workspace    # Default workspace path
├── agents.profiles              # Named profiles (workspace + model override)
├── channels.telegram/discord/whatsapp/feishu/nextcloud_talk
├── providers.openrouter/anthropic/openai/deepseek/groq/gemini/vllm/moonshot/zhipu
├── gateway.host/port            # Gateway bind (default 0.0.0.0:18790)
├── tools.web.search.apiKey      # Brave Search
├── tools.exec.timeout           # Shell timeout (default 60s)
├── tools.restrictToWorkspace    # Sandbox mode
└── logging.level                # Default WARNING
```

## Build Order Rules

**NEVER** skip stations in the buildorder promotion chain. Use `manage.sh`:
```
📝 drafted → 🔍 under-review → 🏢 cross-check → ✅ approved → 📋 queued → 🔨 building → 📦 deployed (→ done/)
```
Promote: `cd ~/DEV/garage/buildorders && bash manage.sh <action> <id>`
Template + gate rules: `garage/buildorders/TEMPLATE.md`
Never manually edit status fields or move files to `done/`.

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Arena Builder — Competitive BO Execution with Insight Harvesting**

A nanobot skill that triggers parallel model competitions whenever Claude Code starts building a Build Order. Two nanobot agents (running different LLMs via SGLang/Ollama) attempt the same BO in isolated sandboxes simultaneously. All three builders (Claude + 2 competitors) produce structured insights that become training data for model fine-tuning.

**Core Value:** Every Build Order Claude Code executes also produces a structured dataset comparing how different models approach the same problem — turning daily work into continuous model improvement.

### Constraints

- **Isolation:** Competitors MUST run in isolated sandboxes (no access to each other's work)
- **Cost:** Competitors use local models (Qwen via Ollama/SGLang) — zero API cost
- **Time:** Competitors get same timeout as Octopus (30 min for GSD mode)
- **No interference:** Arena runs must not block or slow Claude Code's real build
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->
## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
