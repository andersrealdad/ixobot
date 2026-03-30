"""Vault Engine — Reflection & Promotion.

Runs as a scheduled Prefect flow or standalone CLI.

  Hourly  — decay vault.memories (decay_score -= 0.005/hr for unpromoted)
  Daily   — promote importance>=7 memories to ixonaut_hub.crystals
  Weekly  — synthesize memory clusters into insight crystals
            + resurrect decayed memories that match active clusters

Standalone:
    python -m nanobot.vault.reflection promote
    python -m nanobot.vault.reflection decay
    python -m nanobot.vault.reflection synthesize
    python -m nanobot.vault.reflection status
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import psycopg2
import psycopg2.extras
from loguru import logger

from nanobot.vault.config import (
    EMBED_DIM,
    EMBED_MODEL,
    EMBED_URL,
    LLM_MODEL,
    LLM_URL,
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


# ── Synthesis — cluster memories → insight crystals ───────────────────────

SYNTH_MIN_CLUSTER    = int(os.environ.get("VAULT_SYNTH_MIN_CLUSTER", "4"))
SYNTH_SIMILARITY     = float(os.environ.get("VAULT_SYNTH_SIMILARITY", "0.7"))
RESURRECT_DECAY_CEIL = float(os.environ.get("VAULT_RESURRECT_DECAY_CEIL", "0.3"))
RESURRECT_SIMILARITY = float(os.environ.get("VAULT_RESURRECT_SIMILARITY", "0.65"))
SHARED_MEMORY_DB     = Path.home() / "shared-data" / "db" / "shared-memory.db"

SYNTH_PROMPT = """You are Jimmy, the Vault Engine memory synthesizer.
Given a CLUSTER of related memories from the agent system, synthesize them into
a single crystal — one insight that captures the *pattern* across these memories.

Cluster members:
{members}

{resurrection_section}

Output a JSON object:
{{
  "title": "short title (max 15 words)",
  "insight": "one paragraph explaining the pattern, why it matters, and what to watch for",
  "tags": ["relevant", "tags"],
  "severity": "green|yellow|red"
}}

Rules:
- Find the PATTERN, not just a summary. What keeps happening? Why?
- If resurrected memories are present, this is an UNRESOLVED PATTERN — something
  that was forgotten but keeps surfacing. Say so explicitly. Severity should be
  yellow or red.
- Be direct. One paragraph. No filler.

Output ONLY the JSON object."""


@dataclass
class SynthesisResult:
    clusters_found: int = 0
    crystals_created: int = 0
    memories_consumed: int = 0
    resurrections: int = 0
    errors: int = 0


def run_synthesis(pg_password: str | None = None) -> SynthesisResult:
    """Weekly synthesis: cluster related memories → insight crystals.

    1. Build similarity graph from vault.edges
    2. Find connected components with >= SYNTH_MIN_CLUSTER members
    3. For each cluster:
       a. Resurrect: find decayed memories similar to cluster centroid
       b. LLM-synthesize into a crystal
       c. Mark members as consumed_by='synthesis'
       d. Alert Janne on unresolved-pattern crystals
    """
    pg_password = pg_password or _get_pg_password()
    conn = _pg_connect(pg_password)
    result = SynthesisResult()

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # 1. Load candidate memories (have embeddings, not consumed, not promoted)
        cur.execute("""
            SELECT id, topic, summary, category, importance, tags, agent_id,
                   decay_score, created_at
            FROM vault.memories
            WHERE embedding IS NOT NULL
              AND consumed_by IS NULL
              AND promoted_at IS NULL
              AND summary != ''
              AND topic != 'unknown'
            ORDER BY created_at DESC
        """)
        candidates = {str(row["id"]): row for row in cur.fetchall()}

        if len(candidates) < SYNTH_MIN_CLUSTER:
            logger.info(f"Synthesis: only {len(candidates)} candidates, need {SYNTH_MIN_CLUSTER}")
            return result

        # 2. Load edges between candidates
        candidate_ids = list(candidates.keys())
        cur.execute("""
            SELECT from_id::text, to_id::text, weight
            FROM vault.edges
            WHERE from_id::text = ANY(%s)
              AND to_id::text = ANY(%s)
              AND weight >= %s
        """, (candidate_ids, candidate_ids, SYNTH_SIMILARITY))

        edges = cur.fetchall()
        logger.info(f"Synthesis: {len(candidates)} candidates, {len(edges)} edges above {SYNTH_SIMILARITY}")

        # 3. Find connected components via union-find
        clusters = _find_clusters(candidates, edges)
        viable = [c for c in clusters if len(c) >= SYNTH_MIN_CLUSTER]
        result.clusters_found = len(viable)
        logger.info(f"Synthesis: {len(viable)} clusters with >= {SYNTH_MIN_CLUSTER} members")

        # 4. Process each cluster
        for cluster_ids in viable:
            try:
                synth = _synthesize_cluster(conn, cur, cluster_ids, candidates)
                result.crystals_created += 1
                result.memories_consumed += len(cluster_ids)
                result.resurrections += synth.get("resurrections", 0)
                logger.info(
                    f"Synthesis: created crystal '{synth['title']}' "
                    f"from {len(cluster_ids)} memories"
                    + (f" + {synth['resurrections']} resurrected" if synth.get("resurrections") else "")
                )
            except Exception as e:
                conn.rollback()
                result.errors += 1
                logger.error(f"Synthesis: cluster failed: {e}")

        conn.commit()

    except Exception as e:
        conn.rollback()
        logger.error(f"Synthesis run failed: {e}")
        raise
    finally:
        conn.close()

    logger.info(
        f"Synthesis: done — clusters={result.clusters_found}, "
        f"crystals={result.crystals_created}, consumed={result.memories_consumed}, "
        f"resurrected={result.resurrections}, errors={result.errors}"
    )
    return result


def _find_clusters(
    candidates: dict[str, dict],
    edges: list[dict],
) -> list[list[str]]:
    """Union-find connected components from edge list."""
    parent: dict[str, str] = {cid: cid for cid in candidates}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for edge in edges:
        fid, tid = str(edge["from_id"]), str(edge["to_id"])
        if fid in candidates and tid in candidates:
            union(fid, tid)

    groups: dict[str, list[str]] = defaultdict(list)
    for cid in candidates:
        groups[find(cid)].append(cid)

    return list(groups.values())


def _synthesize_cluster(
    conn: psycopg2.extensions.connection,
    cur: psycopg2.extensions.cursor,
    cluster_ids: list[str],
    candidates: dict[str, dict],
) -> dict:
    """Synthesize one cluster into a crystal. Returns metadata dict."""
    members = [candidates[cid] for cid in cluster_ids]

    # ── Resurrection: find decayed memories matching this cluster ──────────
    resurrected = _resurrect(cur, cluster_ids)

    # ── Build LLM prompt ──────────────────────────────────────────────────
    member_text = "\n".join(
        f"- [{m['category']}] {m['topic']}: {m['summary']} "
        f"(importance={m['importance']}, agent={m['agent_id'] or 'system'}, "
        f"{m['created_at'].strftime('%Y-%m-%d')})"
        for m in members
    )

    resurrection_section = ""
    if resurrected:
        resurrection_section = (
            "RESURRECTED MEMORIES (these decayed/were forgotten but match this cluster):\n"
            + "\n".join(
                f"- [RESURRECTED] {r['topic']}: {r['summary']} "
                f"(decay_score={r['decay_score']:.2f}, {r['created_at'].strftime('%Y-%m-%d')})"
                for r in resurrected
            )
        )

    prompt = SYNTH_PROMPT.format(
        members=member_text,
        resurrection_section=resurrection_section,
    )

    # ── Call LLM ──────────────────────────────────────────────────────────
    llm_result = _call_llm_sync(prompt)
    if not llm_result:
        # Fallback: mechanical synthesis
        topics = list({m["topic"] for m in members if m["topic"] != "unknown"})
        llm_result = {
            "title": f"Cluster: {', '.join(topics[:3])}",
            "insight": "; ".join(m["summary"][:100] for m in members[:5] if m["summary"]),
            "tags": ["synthesis", "auto-cluster"],
            "severity": "yellow" if resurrected else "green",
        }

    title = (llm_result.get("title") or "Untitled synthesis")[:200]
    content = llm_result.get("insight") or ""
    tags = list(llm_result.get("tags") or [])
    severity = llm_result.get("severity", "green")

    # Tag appropriately
    for t in ["synthesis", f"cluster-{len(cluster_ids)}"]:
        if t not in tags:
            tags.append(t)
    if resurrected:
        if "unresolved-pattern" not in tags:
            tags.append("unresolved-pattern")
        if "resurrected" not in tags:
            tags.append("resurrected")

    # ── Compute average embedding for the crystal ─────────────────────────
    cur.execute("""
        SELECT avg(embedding)::vector AS centroid
        FROM vault.memories
        WHERE id = ANY(%s::uuid[])
          AND embedding IS NOT NULL
    """, (cluster_ids,))
    row = cur.fetchone()
    centroid = row["centroid"] if row else None

    # ── Insert crystal ────────────────────────────────────────────────────
    source_ids = ",".join(cluster_ids[:10])
    source_file = f"synthesis:{source_ids}"

    cur.execute("""
        INSERT INTO ixonaut_hub.crystals
            (title, content, source_file, tags, embedding, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, now(), now())
        RETURNING id
    """, (title, content, source_file, tags, centroid))
    crystal_id = cur.fetchone()["id"]

    # ── Mark cluster members as consumed ──────────────────────────────────
    cur.execute("""
        UPDATE vault.memories
        SET consumed_by = 'synthesis', consumed_at = now()
        WHERE id = ANY(%s::uuid[])
    """, (cluster_ids,))

    # ── If unresolved pattern, alert Janne via message_bus ────────────────
    if resurrected:
        _alert_overseer(
            f"Unresolved pattern detected: '{title}' — "
            f"{len(cluster_ids)} active memories clustered with "
            f"{len(resurrected)} decayed/forgotten memories. "
            f"Crystal #{crystal_id}. Severity: {severity}."
        )

    return {
        "title": title,
        "crystal_id": crystal_id,
        "severity": severity,
        "resurrections": len(resurrected),
    }


def _resurrect(
    cur: psycopg2.extensions.cursor,
    cluster_ids: list[str],
) -> list[dict]:
    """Find decayed memories whose embeddings are close to the cluster centroid.

    These are the ghosts — things that faded from memory but match what's
    happening now. If they show up, something was never resolved.
    """
    # Compute centroid of active cluster
    cur.execute("""
        SELECT avg(embedding)::vector AS centroid
        FROM vault.memories
        WHERE id = ANY(%s::uuid[])
          AND embedding IS NOT NULL
    """, (cluster_ids,))
    row = cur.fetchone()
    if not row or not row["centroid"]:
        return []

    centroid = row["centroid"]

    # Search for decayed memories similar to centroid
    cur.execute("""
        SELECT id, topic, summary, category, importance, decay_score, created_at,
               1 - (embedding <=> %s::vector) AS similarity
        FROM vault.memories
        WHERE decay_score <= %s
          AND embedding IS NOT NULL
          AND consumed_by IS NULL
          AND id != ALL(%s::uuid[])
          AND summary != ''
          AND 1 - (embedding <=> %s::vector) >= %s
        ORDER BY embedding <=> %s::vector
        LIMIT 10
    """, (centroid, RESURRECT_DECAY_CEIL, cluster_ids,
          centroid, RESURRECT_SIMILARITY, centroid))

    resurrected = [dict(r) for r in cur.fetchall()]
    if resurrected:
        logger.info(
            f"Resurrection: {len(resurrected)} decayed memories match cluster — "
            f"topics: {[r['topic'] for r in resurrected]}"
        )
    return resurrected


def _call_llm_sync(prompt: str) -> dict | None:
    """Synchronous LLM call for synthesis."""
    try:
        resp = httpx.post(
            LLM_URL,
            json={
                "model": LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 1024},
            },
            timeout=120,
        )
        resp.raise_for_status()
        text = resp.json().get("response", "")
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            # Handle wrapper keys
            for key in ("crystal", "insight", "result", "data"):
                if key in parsed and isinstance(parsed[key], dict):
                    return parsed[key]
            if "title" in parsed:
                return parsed
        return None
    except Exception as e:
        logger.error(f"Synthesis LLM call failed: {e}")
        return None


def _alert_overseer(message: str) -> None:
    """Write an alert to message_bus for Janne (overseer)."""
    try:
        if not SHARED_MEMORY_DB.exists():
            return
        conn = sqlite3.connect(str(SHARED_MEMORY_DB), timeout=5)
        conn.execute(
            "INSERT INTO message_bus (from_agent, to_agent, channel, message) "
            "VALUES (?, ?, ?, ?)",
            ("jimmy", "overseer", "vault-alerts", message),
        )
        conn.commit()
        conn.close()
        logger.info(f"Synthesis: alerted overseer — {message[:80]}...")
    except Exception as e:
        logger.warning(f"Synthesis: failed to alert overseer: {e}")


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
    sub.add_parser("promote",    help="Promote worthy memories to crystals now")
    sub.add_parser("decay",      help="Apply decay to unpromoted memories")
    sub.add_parser("synthesize", help="Cluster memories → insight crystals + resurrect")
    sub.add_parser("status",     help="Show vault status")
    sub.add_parser("serve",      help="Register and serve Prefect flows")

    args = parser.parse_args()

    if args.cmd == "promote":
        result = run_promotion()
        print(f"\nPromoted: {result.promoted}  Errors: {result.errors}")
    elif args.cmd == "decay":
        n = run_decay()
        print(f"\nDecay applied to {n} memories")
    elif args.cmd == "synthesize":
        result = run_synthesis()
        print(f"\nClusters: {result.clusters_found}  Crystals: {result.crystals_created}  "
              f"Consumed: {result.memories_consumed}  Resurrected: {result.resurrections}  "
              f"Errors: {result.errors}")
    elif args.cmd == "status":
        print_status()
    elif args.cmd == "serve":
        register_prefect_flows()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
