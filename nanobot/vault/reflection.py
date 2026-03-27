"""Vault Engine — Reflection & Promotion.

Runs as a scheduled Prefect flow or standalone CLI.

  Hourly  — decay vault.memories (decay_score -= 0.005/hr for unpromoted)
  Daily   — promote importance>=7 memories to ixonaut_hub.crystals
  Weekly  — synthesize memory clusters into insight crystals (TODO)

Standalone:
    python -m nanobot.vault.reflection promote
    python -m nanobot.vault.reflection decay
    python -m nanobot.vault.reflection status
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
from loguru import logger

from nanobot.vault.config import (
    EMBED_DIM,
    PG_DB,
    PG_HOST,
    PG_PORT,
    PG_USER,
)

# ── Thresholds ────────────────────────────────────────────────────────────────

PROMOTE_MIN_IMPORTANCE = int(os.environ.get("VAULT_PROMOTE_MIN_IMPORTANCE", "7"))
PROMOTE_MIN_DECAY      = float(os.environ.get("VAULT_PROMOTE_MIN_DECAY", "0.8"))
DECAY_RATE_PER_HOUR    = float(os.environ.get("VAULT_DECAY_RATE", "0.005"))


# ── DB helpers ────────────────────────────────────────────────────────────────

def _pg_connect(pg_password: str) -> psycopg2.extensions.connection:
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB,
        user=PG_USER, password=pg_password,
    )
    conn.autocommit = False
    psycopg2.extras.register_uuid()
    return conn


def _get_pg_password() -> str:
    env_pw = os.environ.get("NANOBOT_PG_PASSWORD")
    if env_pw:
        return env_pw
    sys.path.insert(0, str(Path.home() / "DEV" / "garage" / "infra" / "bw-serve"))
    from secrets_client import get_secret
    return get_secret("postgres-credentials")


# ── Promotion ─────────────────────────────────────────────────────────────────

@dataclass
class PromotionResult:
    promoted: int = 0
    skipped: int = 0
    errors: int = 0


def run_promotion(pg_password: str | None = None) -> PromotionResult:
    """Promote worthy vault.memories to ixonaut_hub.crystals.

    Criteria: importance >= PROMOTE_MIN_IMPORTANCE
              AND decay_score >= PROMOTE_MIN_DECAY
              AND promoted_at IS NULL
    """
    pg_password = pg_password or _get_pg_password()
    conn = _pg_connect(pg_password)
    result = PromotionResult()

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Find memories ready for promotion
        cur.execute("""
            SELECT id, topic, summary, category, importance, tags, embedding, agent_id
            FROM vault.memories
            WHERE importance >= %s
              AND decay_score >= %s
              AND promoted_at IS NULL
            ORDER BY importance DESC, created_at ASC
        """, (PROMOTE_MIN_IMPORTANCE, PROMOTE_MIN_DECAY))

        candidates = cur.fetchall()
        logger.info(f"Reflection: {len(candidates)} memories eligible for promotion")

        for mem in candidates:
            try:
                _promote_one(conn, cur, mem)
                result.promoted += 1
                logger.info(f"Reflection: promoted '{mem['topic']}' (importance={mem['importance']}) → crystal")
            except Exception as e:
                conn.rollback()
                result.errors += 1
                logger.error(f"Reflection: failed to promote '{mem['topic']}': {e}")

        conn.commit()

    except Exception as e:
        conn.rollback()
        logger.error(f"Reflection promotion run failed: {e}")
        raise
    finally:
        conn.close()

    logger.info(f"Reflection: done — promoted={result.promoted}, errors={result.errors}")
    return result


def _promote_one(
    conn: psycopg2.extensions.connection,
    cur: psycopg2.extensions.cursor,
    mem: dict,
) -> None:
    """Insert one memory as a crystal and mark it promoted."""
    title = (mem["topic"] or "Unnamed memory")[:200]

    # Build content: summary + category context
    lines = [mem["summary"] or ""]
    if mem["category"] and mem["category"] != "task":
        lines.append(f"\nCategory: {mem['category']}")
    if mem["agent_id"]:
        lines.append(f"Agent: {mem['agent_id']}")
    content = "\n".join(lines).strip()

    tags = list(mem["tags"] or [])
    for t in ["promoted-from-vault", mem["category"] or "task"]:
        if t and t not in tags:
            tags.append(t)

    source_file = f"vault:{mem['id']}"

    # Copy embedding directly (both tables are vector(1024))
    embedding = mem["embedding"]

    cur.execute("""
        INSERT INTO ixonaut_hub.crystals (title, content, source_file, tags, embedding, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, now(), now())
    """, (title, content, source_file, tags, embedding))

    cur.execute("""
        UPDATE vault.memories SET promoted_at = now() WHERE id = %s
    """, (mem["id"],))


# ── Decay ─────────────────────────────────────────────────────────────────────

def run_decay(pg_password: str | None = None) -> int:
    """Apply hourly decay to unpromoted vault.memories.

    decay_score decreases by DECAY_RATE_PER_HOUR per hour since last access.
    Floors at 0.0 — never negative.
    Promoted memories are exempt from decay.
    """
    pg_password = pg_password or _get_pg_password()
    conn = _pg_connect(pg_password)

    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE vault.memories
            SET decay_score = GREATEST(
                0.0,
                decay_score - (%s * EXTRACT(EPOCH FROM (now() - created_at)) / 3600.0)
            )
            WHERE promoted_at IS NULL
              AND decay_score > 0.0
        """, (DECAY_RATE_PER_HOUR,))
        affected = cur.rowcount
        conn.commit()
        logger.info(f"Reflection: decay applied to {affected} memories")
        return affected
    except Exception as e:
        conn.rollback()
        logger.error(f"Reflection decay run failed: {e}")
        raise
    finally:
        conn.close()


# ── Status ────────────────────────────────────────────────────────────────────

def print_status(pg_password: str | None = None) -> None:
    pg_password = pg_password or _get_pg_password()
    conn = _pg_connect(pg_password)
    try:
        cur = conn.cursor()

        cur.execute("SELECT count(*) FROM vault.memories")
        total = cur.fetchone()[0]

        cur.execute("SELECT count(*) FROM vault.memories WHERE promoted_at IS NOT NULL")
        promoted = cur.fetchone()[0]

        cur.execute("""
            SELECT importance, count(*) FROM vault.memories
            WHERE promoted_at IS NULL
            GROUP BY importance ORDER BY importance DESC
        """)
        pending_by_importance = cur.fetchall()

        cur.execute("SELECT count(*) FROM ixonaut_hub.crystals")
        crystals = cur.fetchone()[0]

        cur.execute("""
            SELECT count(*) FROM vault.memories
            WHERE importance >= %s AND decay_score >= %s AND promoted_at IS NULL
        """, (PROMOTE_MIN_IMPORTANCE, PROMOTE_MIN_DECAY))
        ready = cur.fetchone()[0]

        cur.execute("""
            SELECT created_at FROM ixonaut_hub.crystals ORDER BY created_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        last_crystal = row[0].strftime("%Y-%m-%d %H:%M UTC") if row else "never"

        print(f"\n{'─'*50}")
        print(f" Jimmy — Vault Status")
        print(f"{'─'*50}")
        print(f" vault.memories total:   {total}")
        print(f" already promoted:       {promoted}")
        print(f" ixonaut_hub.crystals:   {crystals}")
        print(f" last crystal:           {last_crystal}")
        print(f"\n Ready to promote now:   {ready}")
        print(f"\n Unpromoted by importance:")
        for imp, count in pending_by_importance:
            marker = " ← eligible" if imp >= PROMOTE_MIN_IMPORTANCE else ""
            print(f"   importance={imp}: {count:>4}{marker}")
        print(f"{'─'*50}\n")

    finally:
        conn.close()


# ── Prefect flows ─────────────────────────────────────────────────────────────

def register_prefect_flows() -> None:
    """Register hourly decay + daily promotion as Prefect flows."""
    try:
        from prefect import flow, serve
        from prefect.schedules import CronSchedule
    except ImportError:
        logger.warning("Prefect not available — skipping flow registration")
        return

    @flow(name="vault-decay-hourly", log_prints=True)
    def vault_decay_flow():
        affected = run_decay()
        print(f"Decay: {affected} memories updated")

    @flow(name="vault-promotion-daily", log_prints=True)
    def vault_promotion_flow():
        result = run_promotion()
        print(f"Promotion: {result.promoted} promoted, {result.errors} errors")

    serve(
        vault_decay_flow.to_deployment(
            name="vault-decay-hourly",
            cron="0 * * * *",
        ),
        vault_promotion_flow.to_deployment(
            name="vault-promotion-daily",
            cron="0 6 * * *",
        ),
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    from loguru import logger as _log
    _log.remove()
    _log.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")

    parser = argparse.ArgumentParser(description="Jimmy Reflection — vault maintenance")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("promote", help="Promote worthy memories to crystals now")
    sub.add_parser("decay",   help="Apply decay to unpromoted memories")
    sub.add_parser("status",  help="Show vault status")
    sub.add_parser("serve",   help="Register and serve Prefect flows")

    args = parser.parse_args()

    if args.cmd == "promote":
        result = run_promotion()
        print(f"\nPromoted: {result.promoted}  Errors: {result.errors}")
    elif args.cmd == "decay":
        n = run_decay()
        print(f"\nDecay applied to {n} memories")
    elif args.cmd == "status":
        print_status()
    elif args.cmd == "serve":
        register_prefect_flows()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
