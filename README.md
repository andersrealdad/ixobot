# IxoBot

AI agent with persistent memory. Built on [nanobot](https://github.com/HKUDS/nanobot).

IxoBot remembers past conversations, promotes important insights to crystals,
and ships with a structured build order workflow (IxoGSD).

## Quick Start

```bash
# Clone
git clone git@github.com:andersrealdad/ixobot.git
cd ixobot

# Install
pip install -e .

# Run (interactive)
ixobot agent

# Run with a name
ixobot agent --name myagent

# Single message
ixobot agent -m "What do you remember about yesterday?"
```

## Persistent Memory

IxoBot stores memories in SQLite by default (`~/.ixobot/memory.db`). No setup required.

The memory pipeline:
1. **Observe** — agent events are watched and captured
2. **Compress** — LLM structures observations into summaries
3. **Store** — persisted to SQLite (or PostgreSQL)
4. **Reflect** — important memories are promoted to crystals
5. **Recall** — crystals and recent memories are loaded into the next session

### Configuration

Default (zero config):
```json
{
  "memory": {
    "backend": "sqlite",
    "path": "~/.ixobot/memory.db"
  }
}
```

PostgreSQL (optional):
```bash
pip install -e ".[brain]"
```
```json
{
  "memory": {
    "backend": "postgres",
    "dsn": "postgresql://user@host:5432/dbname"
  }
}
```

## IxoGSD — Build Order Workflow

A structured workflow for managing work. See [gsd/README.md](gsd/README.md).

```bash
cd gsd
bash manage.sh status    # View board
bash manage.sh board     # Kanban view
```

## Architecture

```
ixobot/
├── nanobot/          # Agent framework (channels, tools, LLM providers)
├── ixobot/           # Product layer (persistent memory)
├── gsd/              # Build order workflow
├── skills/           # Bundled agent skills
└── bridge/           # WhatsApp bridge (Node.js)
```

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## License

MIT
