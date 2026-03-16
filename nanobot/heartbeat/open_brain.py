"""Open Brain integration — semantic memory for nanobot agents.

Provides hooks for the heartbeat service to:
1. Search similar past solutions before starting a task (context enrichment)
2. Capture completed tasks as thoughts (knowledge accumulation)
3. Capture discussion contributions (collective intelligence)
4. Recall vault memories for agent context (importance + recency, SQL-only)
5. Fetch promoted vault memories for heartbeat injection

Connects to PostgreSQL (stacks:5432) + embedding server (localhost:8201).
Fails gracefully — never blocks the heartbeat loop.

Inspired by Nate B Jones' Open Brain architecture.
"""

import json
import os
from typing import Optional

from loguru import logger

# Lazy-loaded connections
_pg_conn = None
_http_client = None

EMBEDDING_URL = os.environ.get("OPEN_BRAIN_EMBEDDING_URL", "http://localhost:8201")
DATABASE_URL = os.environ.get("OPEN_BRAIN_DATABASE_URL", "")
ENABLED = os.environ.get("OPEN_BRAIN_ENABLED", "true").lower() in ("true", "1", "yes")

# How many similar thoughts to inject as context
CONTEXT_LIMIT = int(os.environ.get("OPEN_BRAIN_CONTEXT_LIMIT", "5"))
SIMILARITY_THRESHOLD = float(os.environ.get("OPEN_BRAIN_THRESHOLD", "0.3"))


def _get_db_url() -> str:
    """Resolve database URL, fetching password from vault if needed."""
    if DATABASE_URL:
        return DATABASE_URL
    try:
        import sys
        sys.path.insert(0, "/home/superfuru/DEV/garage/infra/bw-serve")
        from secrets_client import get_secret
        password = get_secret("postgres-credentials")
        return f"postgresql://astrid:{password}@stacks:5432/astrid_memory"
    except Exception as e:
        logger.debug(f"Open Brain: vault unavailable: {e}")
        return ""


def _get_conn():
    """Get or create PostgreSQL connection with pgvector."""
    global _pg_conn
    if _pg_conn is not None:
        try:
            _pg_conn.cursor().execute("SELECT 1")
            return _pg_conn
        except Exception:
            _pg_conn = None

    try:
        import psycopg2
        from pgvector.psycopg2 import register_vector
        url = _get_db_url()
        if not url:
            return None
        _pg_conn = psycopg2.connect(url)
        _pg_conn.autocommit = True
        register_vector(_pg_conn)
        logger.info("Open Brain: connected to PostgreSQL")
        return _pg_conn
    except Exception as e:
        logger.debug(f"Open Brain: DB connection failed: {e}")
        return None


def _get_http():
    """Get or create HTTP client."""
    global _http_client
    if _http_client is None:
        try:
            import httpx
            _http_client = httpx.Client(timeout=15.0)
        except ImportError:
            logger.debug("Open Brain: httpx not available")
            return None
    return _http_client


def _embed(text: str) -> Optional[list[float]]:
    """Generate embedding for text. Returns None on failure."""
    http = _get_http()
    if not http:
        return None
    try:
        resp = http.post(f"{EMBEDDING_URL}/embed", json={"texts": [text]})
        resp.raise_for_status()
        return resp.json()["embeddings"][0]
    except Exception as e:
        logger.debug(f"Open Brain: embedding failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Hook 1: Search before task — inject similar past solutions as context
# ---------------------------------------------------------------------------

def search_context(query: str, agent_name: str | None = None) -> str:
    """Search the Open Brain for relevant prior knowledge.

    Returns a formatted string to inject into the task prompt,
    or empty string if nothing relevant found.
    """
    if not ENABLED:
        return ""

    conn = _get_conn()
    if not conn:
        return ""

    embedding = _embed(query)
    if not embedding:
        return ""

    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM match_thoughts(%s::vector, %s, %s, %s, %s, %s)",
                (str(embedding), SIMILARITY_THRESHOLD, CONTEXT_LIMIT, None, None, None),
            )
            results = cur.fetchall()

        if not results:
            return ""

        lines = ["## Prior Knowledge (from Open Brain)", ""]
        for r in results:
            sim = round(r["similarity"], 2)
            lines.append(f"**[{r['thought_type']}]** (sim={sim}, by {r['agent_name'] or 'unknown'}):")
            # Truncate long content for context injection
            content = r["content"]
            if len(content) > 500:
                content = content[:500] + "..."
            lines.append(content)
            lines.append("")

        logger.info(f"Open Brain: found {len(results)} relevant thought(s) for task context")
        return "\n".join(lines)

    except Exception as e:
        logger.debug(f"Open Brain: search failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Hook 2: Capture completed task — store as thought with embedding
# ---------------------------------------------------------------------------

def capture_task(
    task_id: int,
    title: str,
    description: str | None,
    response: str,
    agent_name: str,
    priority: str | None = None,
) -> bool:
    """Capture a completed task as a thought in the Open Brain.

    Returns True on success, False on failure (never raises).
    """
    if not ENABLED:
        return False

    conn = _get_conn()
    if not conn:
        return False

    # Compose the thought content
    content = f"Task #{task_id}: {title}\n"
    if description:
        content += f"\nDescription: {description}\n"
    content += f"\nSolution:\n{response}"

    # Truncate very long responses
    if len(content) > 4000:
        content = content[:4000] + "\n\n[truncated]"

    embedding = _embed(content)
    if not embedding:
        return False

    summary = f"Task #{task_id}: {title}"
    if len(summary) > 200:
        summary = summary[:197] + "..."

    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.thoughts
                    (content, summary, embedding, thought_type, topics,
                     source, source_id, agent_name, metadata)
                VALUES (%s, %s, %s::vector, 'task_result', '{}',
                        'heartbeat', %s, %s, %s::jsonb)
                ON CONFLICT DO NOTHING
                RETURNING id""",
                (
                    content,
                    summary,
                    str(embedding),
                    f"task_{task_id}",
                    agent_name,
                    json.dumps({"priority": priority, "task_id": task_id}),
                ),
            )
            row = cur.fetchone()
            if row:
                logger.info(f"Open Brain: captured task #{task_id} as thought #{row[0]}")
                return True
            else:
                logger.debug(f"Open Brain: task #{task_id} already captured (duplicate)")
                return True

    except Exception as e:
        logger.debug(f"Open Brain: capture task failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Hook 3: Capture discussion insight
# ---------------------------------------------------------------------------

def capture_discussion(
    discussion_id: int,
    title: str,
    agent_name: str,
    role: str,
    content: str,
) -> bool:
    """Capture a discussion contribution as a thought.

    Returns True on success, False on failure (never raises).
    """
    if not ENABLED:
        return False

    conn = _get_conn()
    if not conn:
        return False

    thought_content = f"Discussion #{discussion_id}: {title}\n\nRole: {role}\n\n{content}"
    if len(thought_content) > 4000:
        thought_content = thought_content[:4000] + "\n\n[truncated]"

    embedding = _embed(thought_content)
    if not embedding:
        return False

    summary = f"Discussion #{discussion_id}: {title} ({role})"
    thought_type = "discussion"

    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.thoughts
                    (content, summary, embedding, thought_type, topics,
                     source, source_id, agent_name, metadata)
                VALUES (%s, %s, %s::vector, %s, '{}',
                        'discussion', %s, %s, %s::jsonb)
                RETURNING id""",
                (
                    thought_content,
                    summary[:200],
                    str(embedding),
                    thought_type,
                    f"discussion_{discussion_id}_{agent_name}",
                    agent_name,
                    json.dumps({"discussion_id": discussion_id, "role": role}),
                ),
            )
            row = cur.fetchone()
            if row:
                logger.info(f"Open Brain: captured discussion #{discussion_id} comment as thought #{row[0]}")
                return True
            return False

    except Exception as e:
        logger.debug(f"Open Brain: capture discussion failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Hook 4: Recall vault memories for ContextBuilder (SQL-only, no embedding)
# ---------------------------------------------------------------------------

VAULT_CONTEXT_LIMIT = int(os.environ.get("VAULT_CONTEXT_LIMIT", "5"))
VAULT_MIN_IMPORTANCE = int(os.environ.get("VAULT_MIN_IMPORTANCE", "5"))


def recall_vault_context(agent_name: str | None = None) -> str:
    """Recall top vault memories for the agent's context window.

    Queries vault.memories by importance + recency (no vector search — embedding
    dimension not yet aligned with embed server). Returns formatted string for
    injection into system prompt, or empty string on failure.

    Args:
        agent_name: Filter by agent_id (also includes agent_id IS NULL for
                    global memories). Pass None to get global memories only.
    """
    if not ENABLED:
        return ""

    conn = _get_conn()
    if not conn:
        return ""

    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT category, topic, summary, importance, agent_id, tags, created_at
                   FROM vault.memories
                   WHERE consumed_by IS NULL
                     AND importance >= %s
                     AND (agent_id = %s OR agent_id IS NULL)
                   ORDER BY importance DESC, created_at DESC
                   LIMIT %s""",
                (VAULT_MIN_IMPORTANCE, agent_name, VAULT_CONTEXT_LIMIT),
            )
            rows = cur.fetchall()

        if not rows:
            return ""

        lines = ["## Vault Insights", ""]
        for r in rows:
            tag_str = f" [{', '.join(r['tags'])}]" if r.get("tags") else ""
            lines.append(
                f"**[{r['category']}]** (importance={r['importance']}{tag_str}): {r['summary']}"
            )
        lines.append("")

        logger.debug(f"Vault: recalled {len(rows)} memories for agent '{agent_name}'")
        return "\n".join(lines)

    except Exception as e:
        logger.debug(f"Vault: recall failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Hook 5: Promoted vault memories for heartbeat injection
# ---------------------------------------------------------------------------

VAULT_HEARTBEAT_LIMIT = int(os.environ.get("VAULT_HEARTBEAT_LIMIT", "3"))


def recall_promoted_vault(agent_name: str | None = None) -> str:
    """Fetch recently promoted vault memories for heartbeat context.

    Returns formatted string listing the top promoted memories, or empty
    string if none found or vault is unavailable.
    """
    if not ENABLED:
        return ""

    conn = _get_conn()
    if not conn:
        return ""

    try:
        import psycopg2.extras
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT category, topic, summary, importance, promoted_at
                   FROM vault.memories
                   WHERE promoted_at IS NOT NULL
                     AND consumed_by IS NULL
                     AND (agent_name = %s OR agent_name IS NULL OR %s IS NULL)
                   ORDER BY promoted_at DESC
                   LIMIT %s""",
                (agent_name, agent_name, VAULT_HEARTBEAT_LIMIT),
            )
            rows = cur.fetchall()

        if not rows:
            return ""

        lines = ["### Vault — Promoted Insights", ""]
        for r in rows:
            lines.append(f"- **[{r['category']}]** {r['summary']} (importance={r['importance']})")
        lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.debug(f"Vault: promoted recall failed: {e}")
        return ""
