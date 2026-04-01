#!/usr/bin/env python3
"""
Insight Harvester — Collect arena insights into PostgreSQL.

Detects completed Build Orders from message_bus, reads their insights.jsonl
files from sandbox directories, and bulk-inserts into ixonaut.arena_build_insights
on stacks:5432 via psql over ssh.

Usage:
    harvest_insights.py [--bo-id BO_ID] [--dry-run]

    No args:     auto-detect and harvest all completed BOs
    --bo-id X:   harvest only BO X (skip completion detection)
    --dry-run:   show what would be harvested without inserting

Stdlib-only: json, os, subprocess, sqlite3, sys, pathlib.
PostgreSQL access via ssh + psql (matching project pattern).
Always exits 0 (error-resilient).
"""

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _sql_escape(value: str) -> str:
    """Escape a string value for safe inclusion in a SQL literal (single-quoted).

    Replaces single quotes with doubled quotes and backslashes with doubled
    backslashes, preventing SQL injection when the caller wraps the result
    in single quotes for psql.
    """
    return value.replace("\\", "\\\\").replace("'", "''")


def _sql_escape_identifier(value: str) -> str:
    """Validate and return a SQL-safe identifier (bo_id, model name, enum value).

    Only allows alphanumeric characters, underscores, and hyphens.
    Raises ValueError for anything else, blocking injection via identifiers.
    """
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Invalid SQL identifier value: {value!r} — "
            "only alphanumeric, underscore, and hyphen are allowed"
        )
    return value


SHARED_DATA = Path.home() / "shared-data"
WORKSHOP = SHARED_DATA / "DEV" / "garage" / "workshop"
SHARED_MEMORY_DB = SHARED_DATA / "db" / "shared-memory.db"


# ---------------------------------------------------------------------------
# Detection: find harvestable BOs from message_bus
# ---------------------------------------------------------------------------


def find_completed_bos() -> list[str]:
    """Query message_bus for arena-build entries and return bo_ids with 2 entries.

    A BO is harvestable when both competitors have posted results (exactly 2 rows).
    """
    if not SHARED_MEMORY_DB.exists():
        print("Harvest: shared-memory.db not found, no BOs to detect", file=sys.stderr)
        return []

    try:
        conn = sqlite3.connect(str(SHARED_MEMORY_DB))
        rows = conn.execute(
            "SELECT metadata FROM message_bus WHERE channel = 'arena-build' ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
    except Exception as e:
        print(f"Harvest: message_bus query failed: {e}", file=sys.stderr)
        return []

    # Group by bo_id
    bo_counts: dict[str, int] = {}
    for (metadata_str,) in rows:
        if not metadata_str:
            continue
        try:
            meta = json.loads(metadata_str)
            bo_id = meta.get("bo_id")
            if bo_id:
                bo_counts[bo_id] = bo_counts.get(bo_id, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue

    # Only harvest BOs where both competitors finished
    return [bo_id for bo_id, count in bo_counts.items() if count >= 2]


# ---------------------------------------------------------------------------
# Deduplication: check if BO already harvested
# ---------------------------------------------------------------------------


def already_harvested(bo_id: str) -> bool:
    # SQL values escaped -- see _sql_escape() and _sql_escape_identifier()
    """Check if bo_id already has rows in ixonaut.arena_build_insights."""
    try:
        esc_id = _sql_escape_identifier(bo_id)
        query = (
            "SELECT COUNT(*) FROM ixonaut.arena_build_insights"
            " WHERE bo_id = '" + esc_id + "'"
        )
        result = subprocess.run(
            [
                "ssh", "stacks",
                "sudo -u postgres psql -d astrid_memory -t -c "
                + '"' + query + '"',
            ],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            count = int(result.stdout.strip())
            return count > 0
    except Exception as e:
        print(f"Harvest: dedup check failed for {bo_id}: {e}", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# Collection: read insights.jsonl from sandbox directories
# ---------------------------------------------------------------------------


def collect_insights(bo_id: str) -> list[tuple[str, list[dict]]]:
    """Find sandbox dirs for bo_id and read their insights.jsonl files.

    Returns list of (model, insights_list) tuples.
    """
    results: list[tuple[str, list[dict]]] = []

    prefix = f"arena-{bo_id}-"
    for sandbox in WORKSHOP.glob(f"{prefix}*/"):
        if not sandbox.is_dir():
            continue
        model = sandbox.name[len(prefix):]
        insights_file = sandbox / "insights.jsonl"
        if not insights_file.exists():
            print(f"Harvest: no insights.jsonl in {sandbox.name}", file=sys.stderr)
            continue

        insights: list[dict] = []
        try:
            for line in insights_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    insights.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Harvest: bad JSON line in {sandbox.name}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"Harvest: error reading {insights_file}: {e}", file=sys.stderr)
            continue

        results.append((model, insights))

    return results


# ---------------------------------------------------------------------------
# Insertion: bulk insert into PostgreSQL via psql over ssh
# ---------------------------------------------------------------------------


def insert_insights(bo_id: str, model: str, insights: list[dict]) -> int:
    # SQL values escaped -- see _sql_escape() and _sql_escape_identifier()
    """Insert insights into PostgreSQL via psql over ssh. Returns count inserted."""
    if not insights:
        return 0

    esc_id = _sql_escape_identifier(bo_id)
    esc_mdl = _sql_escape_identifier(model)

    sql_lines: list[str] = []
    for ins in insights:
        esc_text = _sql_escape(ins.get("text", ""))
        esc_edges = _sql_escape(json.dumps(ins.get("edges", [])))
        esc_sev = _sql_escape_identifier(ins.get("severity", "info"))
        esc_type = _sql_escape_identifier(ins.get("type", "observation"))
        esc_builder = _sql_escape("arena-" + esc_mdl)

        values = (
            "('" + esc_id + "', '" + esc_mdl + "', '" + esc_type + "', '"
            + esc_text + "', '" + esc_edges + "'::jsonb, '" + esc_sev
            + "', '" + esc_builder + "')"
        )
        sql_lines.append(
            "INSERT INTO ixonaut.arena_build_insights "
            "(bo_id, model, insight_type, text, edges, severity, builder_identity) "
            "VALUES " + values + ";"
        )

    sql = "\n".join(sql_lines)
    try:
        result = subprocess.run(
            ["ssh", "stacks", "sudo -u postgres psql -d astrid_memory"],
            input=sql, capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return len(sql_lines)
        else:
            print(f"Harvest: psql insert failed: {result.stderr}", file=sys.stderr)
            return 0
    except Exception as e:
        print(f"Harvest: insert error for {bo_id}/{model}: {e}", file=sys.stderr)
        return 0


# ---------------------------------------------------------------------------
# Summary: post per-model comparison to message_bus
# ---------------------------------------------------------------------------


def _build_breakdown(insights: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    """Compute type and severity counts for a list of insights."""
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for ins in insights:
        t = ins.get("type", "unknown")
        s = ins.get("severity", "info")
        by_type[t] = by_type.get(t, 0) + 1
        by_severity[s] = by_severity.get(s, 0) + 1
    return by_type, by_severity


def _format_counts(counts: dict[str, int]) -> str:
    """Format a dict of counts as 'N key1, N key2, ...'."""
    return ", ".join(f"{v} {k}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))


def post_summary(bo_id: str, model_insights: dict[str, list[dict]], dry_run: bool = False) -> None:
    """Post a per-model comparison summary to message_bus channel arena-build.

    model_insights: {"qwen3-32b": [list of insight dicts], "qwen3-8b": [list of insight dicts]}
    In dry-run mode, prints the summary but does not insert into message_bus.
    """
    if not model_insights:
        return

    # Build metadata and message text
    models_meta: dict[str, dict] = {}
    lines = [f"Arena Harvest BO #{bo_id} -- Comparison Summary", ""]

    for model, insights in sorted(model_insights.items()):
        by_type, by_severity = _build_breakdown(insights)
        total = len(insights)

        models_meta[model] = {
            "total": total,
            "by_type": by_type,
            "by_severity": by_severity,
        }

        lines.append(f"Model: {model}")
        lines.append(f"  Total insights: {total}")
        lines.append(f"  By type: {_format_counts(by_type)}")
        lines.append(f"  By severity: {_format_counts(by_severity)}")
        lines.append("")

    # Delta line
    if len(model_insights) >= 2:
        sorted_models = sorted(model_insights.items(), key=lambda x: -len(x[1]))
        top_model, top_insights = sorted_models[0]
        second_model, second_insights = sorted_models[1]
        delta = len(top_insights) - len(second_insights)
        if delta > 0:
            lines.append(f"Delta: {top_model} produced {delta} more insights")
        elif delta == 0:
            lines.append(f"Delta: {top_model} and {second_model} produced equal insights")
        else:
            lines.append(f"Delta: {second_model} produced {-delta} more insights")

    message = "\n".join(lines)

    metadata = json.dumps({
        "bo_id": bo_id,
        "type": "harvest_summary",
        "models": models_meta,
    })

    if dry_run:
        print(f"\n{message}")
        print(f"\n  [dry-run] Summary NOT posted to message_bus")
        return

    try:
        conn = sqlite3.connect(str(SHARED_MEMORY_DB))
        conn.execute(
            "INSERT INTO message_bus "
            "(from_agent, to_agent, channel, message, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            ("insight-harvester", "*", "arena-build", message, metadata),
        )
        conn.commit()
        conn.close()
        print(f"  Summary posted to message_bus for BO {bo_id}")
    except Exception as e:
        print(f"Harvest: summary post failed for {bo_id}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Harvest arena insights from sandbox dirs into PostgreSQL.

    Auto-detects completed BOs from message_bus, or harvests a specific BO
    with --bo-id. In --dry-run mode, shows what would be harvested.
    """
    try:
        args = sys.argv[1:]
        dry_run = "--dry-run" in args
        bo_id_flag = None

        # Parse --bo-id
        for i, arg in enumerate(args):
            if arg == "--bo-id" and i + 1 < len(args):
                bo_id_flag = args[i + 1]
                break

        mode_label = " (dry-run)" if dry_run else ""
        print(f"Harvest: starting insight collection{mode_label}")

        # Determine which BOs to harvest
        if bo_id_flag:
            bo_ids = [bo_id_flag]
            print(f"Harvest: targeting BO {bo_id_flag}")
        else:
            bo_ids = find_completed_bos()
            if not bo_ids:
                print("Harvest: no completed BOs found in message_bus")
                return
            print(f"Harvest: found {len(bo_ids)} completed BO(s): {', '.join(bo_ids)}")

        total_harvested = 0

        for bo_id in bo_ids:
            # Dedup check (skip in dry-run to still show what would happen)
            if not dry_run and already_harvested(bo_id):
                print(f"Harvest: BO {bo_id} already harvested, skipping")
                continue

            # Collect insights from sandbox dirs
            collected = collect_insights(bo_id)
            if not collected:
                print(f"Harvest: no insights found for BO {bo_id}")
                continue

            # Build dict for summary: model -> insights list
            bo_model_insights: dict[str, list[dict]] = {}

            for model, insights in collected:
                bo_model_insights[model] = insights
                if dry_run:
                    print(f"  [dry-run] BO {bo_id} / {model}: {len(insights)} insights")
                    for ins in insights[:3]:
                        print(f"    - [{ins.get('type', '?')}] {ins.get('text', '')[:80]}")
                    if len(insights) > 3:
                        print(f"    ... and {len(insights) - 3} more")
                else:
                    count = insert_insights(bo_id, model, insights)
                    print(f"  BO {bo_id} / {model}: {count} insights inserted")
                    total_harvested += count

            # Post comparison summary for this BO
            post_summary(bo_id, bo_model_insights, dry_run=dry_run)

        # Final status
        if dry_run:
            print(f"\nHarvest dry-run complete. Use without --dry-run to insert.")
        else:
            print(f"\nHarvest complete: {total_harvested} total insights inserted")

    except Exception as e:
        print(f"Harvest: fatal error: {e}", file=sys.stderr)

    # Always exit 0
    sys.exit(0)


if __name__ == "__main__":
    main()
