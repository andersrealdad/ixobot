---
name: arena-builder
description: Execute a Build Order in an isolated sandbox using a local model (Qwen), producing structured insights.jsonl output.
user_invocable: false
---

# Arena Builder

You are executing an arena competition task. A Build Order has been assigned to you for isolated execution using a local model. Your job is to run the build in a sandbox and produce structured insights.

## Overview

Arena tasks arrive via `task_queue` rows inserted by `arena_trigger.py`. Each task contains a JSON payload with the Build Order details and assigned model. You execute the build using `agent-gsd.sh` in an isolated sandbox, collect insights from the output, and report results to `message_bus`.

A helper script at `nanobot/skills/arena-builder/scripts/arena_run.py` automates steps 2-5 below and can be called directly:

```bash
python3 nanobot/skills/arena-builder/scripts/arena_run.py '<task_description_json>'
```

## Step 1: Parse the Task Description

The `task_queue` row's `description` field is a JSON string. Parse it with `json.loads()`:

```python
import json
task = json.loads(description)
bo_id = task["bo_id"]           # e.g. "054"
bo_filepath = task["bo_filepath"]  # e.g. "/home/superfuru/DEV/garage/buildorders/054-halen.md"
model = task["model"]           # "qwen3-32b" or "qwen3-8b"
instruks = task["instruks"]     # stripped build order text
```

All four keys (`bo_id`, `bo_filepath`, `model`, `instruks`) must be present.

## Step 2: Create Sandbox

Create an isolated sandbox directory:

```
~/shared-data/DEV/garage/workshop/arena-{bo_id}-{model}/
```

For example: `~/shared-data/DEV/garage/workshop/arena-054-qwen3-32b/`

If the directory already exists, remove it and recreate (idempotent runs). Write the `instruks` value to `instruks.md` in the sandbox root.

```bash
rm -rf ~/shared-data/DEV/garage/workshop/arena-054-qwen3-32b/
mkdir -p ~/shared-data/DEV/garage/workshop/arena-054-qwen3-32b/
```

## Step 3: Run the Build

Execute `agent-gsd.sh` from the sandbox directory with the assigned model:

```bash
cd ~/shared-data/DEV/garage/workshop/arena-{bo_id}-{model}/
OCTOPUS_MODEL={model} OCTOPUS_ORDER_ID={bo_id} ~/DEV/garage/infra/octopus/agent-gsd.sh instruks.md result.json quick
```

- **Mode:** `quick` (single-phase, light planning)
- **Timeout:** 30 minutes maximum
- **Auth:** Uses OAuth/MAX session (no API key needed)
- **Exit codes:** 0 = completed, 1 = error, 2 = flagged

## Step 4: Collect Insights

After `agent-gsd.sh` completes (or fails), scan the sandbox and create `insights.jsonl` in the sandbox root. Each line is a JSON object:

```json
{"type": "observation|decision|warning|pattern|suggestion", "text": "...", "edges": ["file.py", "concept"], "severity": "info|low|medium|high|critical"}
```

**Insight sources:**
- Read `result.json` if it exists -- extract status and key decisions as observation insights
- Read `DONE.md` if it exists -- create a decision insight from its content
- Read `FLAG.md` if it exists -- create a warning insight with severity `high`
- Scan `.planning/` for any `*-SUMMARY.md` files -- create observation insights from accomplishments
- List all files created/modified in the sandbox -- each is an observation insight (severity `info`)
- If exit code is non-zero and no `FLAG.md` exists -- create a warning insight with severity `critical` describing the failure

## Step 5: Report Result

Post the result to `message_bus` in `shared-memory.db`:

```sql
INSERT INTO message_bus (from_agent, to_agent, channel, message, metadata)
VALUES ('{agent_name}', '*', 'arena-build', '{status message}', '{json metadata}')
```

**Metadata JSON:**
```json
{"bo_id": "054", "model": "qwen3-32b", "status": "completed|flagged|error", "insight_count": 12, "duration_s": 340.5}
```

Status mapping from exit code: 0 = `completed`, 2 = `flagged`, anything else = `error`.

## Error Handling

If `agent-gsd.sh` fails (exit 1) or times out (30 minutes):

1. Mark status as `error`
2. Write one insight with `type: "warning"`, `severity: "critical"` describing the failure
3. Still post to `message_bus` with the error status
4. Do NOT retry -- mark as error and move on

The arena is designed to be error-resilient. A competitor failing is valid data (it tells us the model could not complete the BO).
