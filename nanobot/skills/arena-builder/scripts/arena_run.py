#!/usr/bin/env python3
"""
Arena Run — Execute a Build Order in an isolated sandbox.

Standalone script (stdlib only) that automates the arena execution flow:
parse task -> create sandbox -> run agent-gsd.sh -> collect insights -> post result.

Usage:
    arena_run.py <task_description_json>
    arena_run.py /path/to/task.json

The argument is either a JSON string (from task_queue description field)
or a path to a file containing the JSON.

Self-contained: no imports from nanobot, octopus, or any non-stdlib package.
Exits 0 on ALL errors — must never break the arena pipeline.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHARED_DATA = Path.home() / "shared-data"
WORKSHOP = SHARED_DATA / "DEV" / "garage" / "workshop"
AGENT_GSD = Path.home() / "DEV" / "garage" / "infra" / "octopus" / "agent-gsd.sh"
SHARED_MEMORY_DB = SHARED_DATA / "db" / "shared-memory.db"
TIMEOUT_S = 1800  # 30 minutes


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


def parse_task(task_json: str) -> dict:
    """Parse task description JSON string or file path.

    Accepts either a raw JSON string with keys bo_id, bo_filepath, model,
    instruks, or a path to a file containing such JSON.

    Returns the parsed dict. Raises ValueError if required keys are missing.
    """
    # Try as file path first
    candidate = Path(task_json)
    if candidate.is_file():
        raw = candidate.read_text()
    else:
        raw = task_json

    data = json.loads(raw)
    required = {"bo_id", "bo_filepath", "model", "instruks"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Missing required keys: {missing}")
    return data


def create_sandbox(bo_id: str, model: str, instruks: str) -> Path:
    """Create an isolated sandbox directory for the competitor.

    Path: WORKSHOP / arena-{bo_id}-{model}/
    If it already exists, removes and recreates (idempotent).
    Writes instruks.md with the build order text.

    Returns the sandbox path.
    """
    sandbox = WORKSHOP / f"arena-{bo_id}-{model}"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)

    instruks_file = sandbox / "instruks.md"
    instruks_file.write_text(instruks)

    return sandbox


def run_agent_gsd(sandbox: Path, bo_id: str, model: str) -> tuple[int, float]:
    """Run agent-gsd.sh in the sandbox with the assigned model.

    Returns (exit_code, duration_seconds).
    On timeout returns (1, TIMEOUT_S).
    On other errors returns (1, elapsed).
    """
    env = os.environ.copy()
    env["OCTOPUS_MODEL"] = model
    env["OCTOPUS_ORDER_ID"] = bo_id

    start = time.monotonic()
    try:
        result = subprocess.run(
            [str(AGENT_GSD), "instruks.md", "result.json", "quick"],
            cwd=str(sandbox),
            env=env,
            timeout=TIMEOUT_S,
            capture_output=True,
            text=True,
        )
        elapsed = time.monotonic() - start
        return (result.returncode, elapsed)
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        print(f"Arena: agent-gsd.sh timed out after {TIMEOUT_S}s", file=sys.stderr)
        return (1, elapsed)
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"Arena: agent-gsd.sh error: {e}", file=sys.stderr)
        return (1, elapsed)


def collect_insights(
    sandbox: Path, bo_id: str, model: str, exit_code: int, duration_s: float
) -> list[dict]:
    """Scan the sandbox and build a list of structured insights.

    Each insight dict has: type, text, edges, severity.
    """
    insights: list[dict] = []

    # result.json
    result_file = sandbox / "result.json"
    if result_file.exists():
        try:
            result_data = json.loads(result_file.read_text())
            status = result_data.get("status", "unknown")
            insights.append({
                "type": "observation",
                "text": f"agent-gsd.sh result: status={status}",
                "edges": ["result.json"],
                "severity": "info",
            })
            # Extract decisions if present
            for key in ("decisions", "key_decisions"):
                if key in result_data and isinstance(result_data[key], list):
                    for dec in result_data[key]:
                        insights.append({
                            "type": "decision",
                            "text": str(dec),
                            "edges": ["result.json"],
                            "severity": "low",
                        })
        except (json.JSONDecodeError, Exception) as e:
            insights.append({
                "type": "warning",
                "text": f"Could not parse result.json: {e}",
                "edges": ["result.json"],
                "severity": "medium",
            })

    # DONE.md
    done_file = sandbox / "DONE.md"
    if done_file.exists():
        try:
            content = done_file.read_text()[:500]
            insights.append({
                "type": "decision",
                "text": f"Build completed: {content}",
                "edges": ["DONE.md"],
                "severity": "info",
            })
        except Exception:
            pass

    # FLAG.md
    flag_file = sandbox / "FLAG.md"
    if flag_file.exists():
        try:
            content = flag_file.read_text()[:500]
            insights.append({
                "type": "warning",
                "text": f"Build flagged: {content}",
                "edges": ["FLAG.md"],
                "severity": "high",
            })
        except Exception:
            pass

    # .planning/*-SUMMARY.md files
    planning_dir = sandbox / ".planning"
    if planning_dir.exists():
        for summary in planning_dir.rglob("*-SUMMARY.md"):
            try:
                content = summary.read_text()[:500]
                insights.append({
                    "type": "observation",
                    "text": f"GSD summary ({summary.name}): {content}",
                    "edges": [str(summary.relative_to(sandbox))],
                    "severity": "info",
                })
            except Exception:
                pass

    # All files in sandbox (one insight per file)
    try:
        for root, _dirs, files in os.walk(sandbox):
            for fname in files:
                fpath = Path(root) / fname
                rel = str(fpath.relative_to(sandbox))
                # Skip the insights file itself and instruks
                if rel in ("insights.jsonl", "instruks.md"):
                    continue
                insights.append({
                    "type": "observation",
                    "text": f"File created: {rel}",
                    "edges": [rel],
                    "severity": "info",
                })
    except Exception:
        pass

    # Failure insight (if non-zero exit and no FLAG.md)
    if exit_code != 0 and not flag_file.exists():
        insights.append({
            "type": "warning",
            "text": f"agent-gsd.sh failed with exit code {exit_code} after {round(duration_s)}s",
            "edges": [f"arena-{bo_id}-{model}"],
            "severity": "critical",
        })

    return insights


def write_insights(sandbox: Path, insights: list[dict]) -> Path:
    """Write insights as JSON Lines to sandbox/insights.jsonl.

    Returns the file path.
    """
    output = sandbox / "insights.jsonl"
    with open(output, "w") as f:
        for insight in insights:
            f.write(json.dumps(insight) + "\n")
    return output


def post_result(
    agent_name: str,
    bo_id: str,
    model: str,
    status: str,
    insight_count: int,
    duration_s: float,
) -> None:
    """Post arena result to message_bus in shared-memory.db."""
    metadata = json.dumps({
        "bo_id": bo_id,
        "model": model,
        "status": status,
        "insight_count": insight_count,
        "duration_s": round(duration_s, 1),
    })
    message = (
        f"Arena BO #{bo_id} ({model}): {status} "
        f"- {insight_count} insights in {round(duration_s)}s"
    )

    try:
        conn = sqlite3.connect(str(SHARED_MEMORY_DB))
        conn.execute(
            "INSERT INTO message_bus "
            "(from_agent, to_agent, channel, message, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_name, "*", "arena-build", message, metadata),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Arena: message_bus post failed: {e}", file=sys.stderr)


def main() -> None:
    """Orchestrate the full arena execution flow.

    Parse task -> create sandbox -> run agent-gsd.sh ->
    collect insights -> write insights -> post result.

    Always exits 0 (error-resilient pattern).
    """
    try:
        if len(sys.argv) < 2:
            print(
                "Usage: arena_run.py <task_description_json>",
                file=sys.stderr,
            )
            sys.exit(0)

        task = parse_task(sys.argv[1])
        bo_id = task["bo_id"]
        model = task["model"]
        instruks = task["instruks"]

        agent_name = os.environ.get("NANOBOT_AGENT_NAME", "arena-competitor")

        print(f"Arena: starting BO #{bo_id} with {model}")

        # Create sandbox
        sandbox = create_sandbox(bo_id, model, instruks)
        print(f"Arena: sandbox at {sandbox}")

        # Run the build
        exit_code, duration_s = run_agent_gsd(sandbox, bo_id, model)

        # Determine status
        if exit_code == 0:
            status = "completed"
        elif exit_code == 2:
            status = "flagged"
        else:
            status = "error"

        print(f"Arena: agent-gsd.sh exited {exit_code} ({status}) in {round(duration_s)}s")

        # Collect and write insights
        insights = collect_insights(sandbox, bo_id, model, exit_code, duration_s)
        insights_file = write_insights(sandbox, insights)
        print(f"Arena: {len(insights)} insights written to {insights_file}")

        # Post result to message_bus
        post_result(agent_name, bo_id, model, status, len(insights), duration_s)
        print(f"Arena: result posted to message_bus (arena-build)")

    except Exception as e:
        print(f"Arena: fatal error: {e}", file=sys.stderr)
        # Error-resilient: always exit 0
        sys.exit(0)


if __name__ == "__main__":
    main()
