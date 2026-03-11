"""Heartbeat service - periodic agent wake-up to check for tasks."""

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

# Default interval: 30 minutes
DEFAULT_HEARTBEAT_INTERVAL_S = 30 * 60

# Default shared-memory DB path
DEFAULT_SHARED_MEMORY_DB = Path.home() / "shared-data" / "db" / "shared-memory.db"

# The prompt sent to agent during heartbeat
HEARTBEAT_PROMPT = """Read HEARTBEAT.md in your workspace (if it exists).
Follow any instructions or tasks listed there.
If nothing needs attention, reply with just: HEARTBEAT_OK"""

# Prompt template for task_queue work
TASK_QUEUE_PROMPT = """You have {count} pending task(s) from the task queue. Execute them in priority order.

{tasks}

For each task:
1. Claim it (update status to 'in_progress')
2. Execute the work described
3. Report the result
4. If you cannot complete it, explain why

When done, update the task status to 'done' or 'failed' with a result summary."""

# Token that indicates "nothing to do"
HEARTBEAT_OK_TOKEN = "HEARTBEAT_OK"

# Max tasks to process per heartbeat tick
MAX_TASKS_PER_TICK = 3


def _is_heartbeat_empty(content: str | None) -> bool:
    """Check if HEARTBEAT.md has no actionable content."""
    if not content:
        return True

    # Lines to skip: empty, headers, HTML comments, empty checkboxes
    skip_patterns = {"- [ ]", "* [ ]", "- [x]", "* [x]"}

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("<!--") or line in skip_patterns:
            continue
        return False  # Found actionable content

    return True


def _fetch_pending_tasks(db_path: Path, agent_name: str, limit: int = MAX_TASKS_PER_TICK) -> list[dict]:
    """Fetch pending tasks from shared-memory task_queue for this agent."""
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT id, title, description, source_agent, priority, gitea_repo, gitea_issue
               FROM task_queue
               WHERE target_agent = ? AND status = 'pending'
               ORDER BY
                 CASE priority
                   WHEN 'p0-critical' THEN 0
                   WHEN 'p1-high' THEN 1
                   WHEN 'p2-medium' THEN 2
                   WHEN 'p3-low' THEN 3
                 END,
                 created_at ASC
               LIMIT ?""",
            (agent_name, limit),
        ).fetchall()
        tasks = [dict(r) for r in rows]
        conn.close()
        return tasks
    except Exception as e:
        logger.warning(f"Heartbeat: failed to read task_queue: {e}")
        return []


def _claim_task(db_path: Path, task_id: int, agent_name: str) -> bool:
    """Claim a task by setting status to 'in_progress'."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute(
            """UPDATE task_queue
               SET status = 'claimed', claimed_by = ?, updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'pending'""",
            (agent_name, task_id),
        )
        conn.commit()
        changed = conn.total_changes
        conn.close()
        return changed > 0
    except Exception as e:
        logger.warning(f"Heartbeat: failed to claim task {task_id}: {e}")
        return False


def _format_tasks_for_prompt(tasks: list[dict]) -> str:
    """Format task_queue rows into a readable prompt section."""
    lines = []
    for t in tasks:
        lines.append(f"### Task #{t['id']} [{t['priority']}]")
        lines.append(f"**Title:** {t['title']}")
        if t.get("description"):
            lines.append(f"**Description:** {t['description']}")
        if t.get("gitea_repo"):
            issue = f" #{t['gitea_issue']}" if t.get("gitea_issue") else ""
            lines.append(f"**Repo:** {t['gitea_repo']}{issue}")
        lines.append(f"**From:** {t['source_agent']}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discussion protocol — agents deliberate before executing
# ---------------------------------------------------------------------------

# Agents and what they weigh in on
AGENT_EXPERTISE = {
    "dario": ["implementation", "feasibility", "infrastructure"],
    "librarian": ["memory", "history", "documentation", "drift"],
    "robocop": ["security", "compliance", "ports", "secrets"],
    "overseer": ["quality", "review", "standards"],
    "astrid": ["coordination", "context", "orchestration"],
}

# How many unique agent comments before a discussion can be synthesized
MIN_COMMENTS_FOR_PROPOSAL = 2

DISCUSSION_REVIEW_PROMPT = """An open discussion needs your input. Review the problem and prior comments, then contribute your perspective based on your expertise.

## Discussion #{disc_id}: {title}

**Problem:**
{description}

**Comments so far:**
{comments}

**Your role:** {agent_name}
**Your expertise:** {expertise}

Respond with your analysis. Focus on:
1. Is this a real problem or noise?
2. What is the ROBUST solution (not a quick fix)?
3. What are the risks of acting vs. not acting?
4. Any dependencies or things others missed?

Keep it concise. End with a clear recommendation."""

DISCUSSION_SYNTHESIZE_PROMPT = """All agents have weighed in on this discussion. Synthesize their input into a single actionable proposal for Anders to approve or reject.

## Discussion #{disc_id}: {title}

**Problem:**
{description}

**Agent comments:**
{comments}

Write a proposal that:
1. States the problem clearly (1-2 sentences)
2. Recommends ONE robust solution (not a quick fix)
3. Lists concrete steps to implement
4. Notes any dissenting opinions or risks
5. Estimates scope (small/medium/large change)

Format as a clean proposal Anders can approve with one word."""


def _fetch_open_discussions(db_path: Path, agent_name: str, limit: int = 2) -> list[dict]:
    """Fetch open discussions this agent hasn't commented on yet."""
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT d.id, d.title, d.trigger_source, d.status, d.created_by, d.created_at
               FROM discussions d
               WHERE d.status IN ('open', 'discussing')
                 AND d.id NOT IN (
                   SELECT discussion_id FROM discussion_comments WHERE agent_name = ?
                 )
               ORDER BY d.created_at ASC
               LIMIT ?""",
            (agent_name, limit),
        ).fetchall()
        discussions = [dict(r) for r in rows]
        conn.close()
        return discussions
    except Exception as e:
        logger.warning(f"Heartbeat: failed to read discussions: {e}")
        return []


def _fetch_discussion_comments(db_path: Path, discussion_id: int) -> list[dict]:
    """Fetch all comments for a discussion."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT agent_name, role, content, created_at
               FROM discussion_comments
               WHERE discussion_id = ?
               ORDER BY created_at ASC""",
            (discussion_id,),
        ).fetchall()
        comments = [dict(r) for r in rows]
        conn.close()
        return comments
    except Exception as e:
        logger.warning(f"Heartbeat: failed to read comments for discussion {discussion_id}: {e}")
        return []


def _add_discussion_comment(db_path: Path, discussion_id: int, agent_name: str, role: str, content: str) -> bool:
    """Add a comment to a discussion."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute(
            """INSERT INTO discussion_comments (discussion_id, agent_name, role, content)
               VALUES (?, ?, ?, ?)""",
            (discussion_id, agent_name, role, content[:4000]),
        )
        # Update discussion status to 'discussing' if it was 'open'
        conn.execute(
            """UPDATE discussions SET status = 'discussing'
               WHERE id = ? AND status = 'open'""",
            (discussion_id,),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"Heartbeat: failed to add comment to discussion {discussion_id}: {e}")
        return False


def _count_unique_commenters(db_path: Path, discussion_id: int) -> int:
    """Count unique agents that have commented on a discussion."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        count = conn.execute(
            "SELECT COUNT(DISTINCT agent_name) FROM discussion_comments WHERE discussion_id = ?",
            (discussion_id,),
        ).fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


def _set_discussion_proposal(db_path: Path, discussion_id: int, proposal: str) -> bool:
    """Set the proposal on a discussion and mark it as proposed."""
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute(
            """UPDATE discussions
               SET status = 'proposed', proposal = ?, concluded_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (proposal[:8000], discussion_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"Heartbeat: failed to set proposal on discussion {discussion_id}: {e}")
        return False


def _format_comments_for_prompt(comments: list[dict]) -> str:
    """Format discussion comments into readable text."""
    if not comments:
        return "(No comments yet — you are first.)"
    lines = []
    for c in comments:
        lines.append(f"**{c['agent_name']}** ({c['role']}):")
        lines.append(c["content"])
        lines.append("")
    return "\n".join(lines)


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Checks two sources each tick:
    1. HEARTBEAT.md in the workspace (manual/override tasks)
    2. task_queue in shared-memory.db (automated pipeline tasks)

    If neither has work, the tick is skipped silently.
    """

    def __init__(
        self,
        workspace: Path,
        on_heartbeat: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S,
        enabled: bool = True,
        agent_name: str | None = None,
        shared_memory_db: Path | None = None,
    ):
        self.workspace = workspace
        self.on_heartbeat = on_heartbeat
        self.interval_s = interval_s
        self.enabled = enabled
        self.agent_name = agent_name
        self.shared_memory_db = shared_memory_db or DEFAULT_SHARED_MEMORY_DB
        self._running = False
        self._task: asyncio.Task | None = None
    
    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"
    
    def _read_heartbeat_file(self) -> str | None:
        """Read HEARTBEAT.md content."""
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text()
            except Exception:
                return None
        return None
    
    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return

        self._running = True
        self._register_heartbeat("online", "heartbeat starting")
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Heartbeat started (every {self.interval_s}s)")
    
    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        self._register_heartbeat("offline")
        if self._task:
            self._task.cancel()
            self._task = None
    
    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
    
    async def _tick(self) -> None:
        """Execute a single heartbeat tick.

        Checks HEARTBEAT.md first (manual tasks), then task_queue (automated).
        Either source can trigger the agent; both are checked every tick.
        """
        has_work = False

        # --- Source 1: HEARTBEAT.md ---
        content = self._read_heartbeat_file()
        if not _is_heartbeat_empty(content):
            has_work = True
            logger.info("Heartbeat: found tasks in HEARTBEAT.md")
            if self.on_heartbeat:
                try:
                    response = await self.on_heartbeat(HEARTBEAT_PROMPT)
                    if HEARTBEAT_OK_TOKEN.replace("_", "") in response.upper().replace("_", ""):
                        logger.info("Heartbeat: HEARTBEAT.md — OK (no action needed)")
                    else:
                        logger.info("Heartbeat: HEARTBEAT.md — completed task")
                except Exception as e:
                    logger.error(f"Heartbeat: HEARTBEAT.md execution failed: {e}")

        # --- Source 2: task_queue in shared-memory.db ---
        if self.agent_name:
            tasks = _fetch_pending_tasks(self.shared_memory_db, self.agent_name)
            if tasks:
                has_work = True
                logger.info(f"Heartbeat: {len(tasks)} pending task(s) in queue for {self.agent_name}")

                # Claim tasks before dispatching
                claimed = []
                for t in tasks:
                    if _claim_task(self.shared_memory_db, t["id"], self.agent_name):
                        claimed.append(t)
                    else:
                        logger.debug(f"Heartbeat: task #{t['id']} already claimed by another agent")

                if claimed and self.on_heartbeat:
                    prompt = TASK_QUEUE_PROMPT.format(
                        count=len(claimed),
                        tasks=_format_tasks_for_prompt(claimed),
                    )
                    try:
                        response = await self.on_heartbeat(prompt)
                        logger.info(f"Heartbeat: processed {len(claimed)} task(s) from queue")
                        # Update completed tasks
                        self._mark_tasks_done(claimed, response)
                    except Exception as e:
                        logger.error(f"Heartbeat: task_queue execution failed: {e}")
                        self._mark_tasks_failed(claimed, str(e))

        # --- Source 3: Open discussions needing this agent's input ---
        if self.agent_name:
            await self._check_discussions()

        # --- Update agent_heartbeat in shared-memory.db ---
        status = "active" if has_work else "online"
        task_desc = "processing tasks" if has_work else None
        self._register_heartbeat(status, task_desc)

        if not has_work:
            logger.debug("Heartbeat: no tasks (HEARTBEAT.md empty, queue empty)")
    
    async def _check_discussions(self) -> None:
        """Check for open discussions and contribute or synthesize."""
        discussions = _fetch_open_discussions(self.shared_memory_db, self.agent_name)
        if not discussions:
            return

        for disc in discussions:
            disc_id = disc["id"]
            comments = _fetch_discussion_comments(self.shared_memory_db, disc_id)
            unique_commenters = _count_unique_commenters(self.shared_memory_db, disc_id)

            # If enough agents have commented, synthesize a proposal (librarian role)
            if unique_commenters >= MIN_COMMENTS_FOR_PROPOSAL and self.agent_name == "librarian":
                logger.info(f"Discussion #{disc_id}: synthesizing proposal ({unique_commenters} contributors)")
                prompt = DISCUSSION_SYNTHESIZE_PROMPT.format(
                    disc_id=disc_id,
                    title=disc["title"],
                    description=disc.get("trigger_source") or disc["title"],
                    comments=_format_comments_for_prompt(comments),
                )
                if self.on_heartbeat:
                    try:
                        response = await self.on_heartbeat(prompt)
                        _set_discussion_proposal(self.shared_memory_db, disc_id, response)
                        _add_discussion_comment(self.shared_memory_db, disc_id, self.agent_name, "synthesizer", response)
                        logger.info(f"Discussion #{disc_id}: proposal ready for approval")
                    except Exception as e:
                        logger.error(f"Discussion #{disc_id}: synthesis failed: {e}")
            else:
                # Contribute this agent's perspective
                expertise = AGENT_EXPERTISE.get(self.agent_name, ["general"])
                logger.info(f"Discussion #{disc_id}: {self.agent_name} contributing ({', '.join(expertise)})")
                prompt = DISCUSSION_REVIEW_PROMPT.format(
                    disc_id=disc_id,
                    title=disc["title"],
                    description=disc.get("trigger_source") or disc["title"],
                    comments=_format_comments_for_prompt(comments),
                    agent_name=self.agent_name,
                    expertise=", ".join(expertise),
                )
                if self.on_heartbeat:
                    try:
                        response = await self.on_heartbeat(prompt)
                        _add_discussion_comment(self.shared_memory_db, disc_id, self.agent_name, "reviewer", response)
                        logger.info(f"Discussion #{disc_id}: {self.agent_name} commented")
                    except Exception as e:
                        logger.error(f"Discussion #{disc_id}: comment failed: {e}")

    def _mark_tasks_done(self, tasks: list[dict], response: str) -> None:
        """Mark claimed tasks as done with the agent's response."""
        try:
            conn = sqlite3.connect(str(self.shared_memory_db), timeout=5)
            # Truncate response to avoid bloating the DB
            result = response[:2000] if response else ""
            for t in tasks:
                conn.execute(
                    """UPDATE task_queue
                       SET status = 'done', result = ?, completed_at = CURRENT_TIMESTAMP,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (result, t["id"]),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Heartbeat: failed to mark tasks done: {e}")

    def _mark_tasks_failed(self, tasks: list[dict], error: str) -> None:
        """Mark claimed tasks as failed."""
        try:
            conn = sqlite3.connect(str(self.shared_memory_db), timeout=5)
            for t in tasks:
                conn.execute(
                    """UPDATE task_queue
                       SET status = 'failed', result = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (error[:500], t["id"]),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Heartbeat: failed to mark tasks failed: {e}")

    def _register_heartbeat(self, status: str = "online", current_task: str | None = None) -> None:
        """Write agent heartbeat to shared-memory.db so portals can track liveness."""
        if not self.agent_name:
            return
        try:
            conn = sqlite3.connect(str(self.shared_memory_db), timeout=5)
            conn.execute(
                """INSERT INTO agent_heartbeat (agent_id, agent_type, status, current_task, last_heartbeat, started_at)
                   VALUES (?, 'nanobot', ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                   ON CONFLICT(agent_id) DO UPDATE SET
                       status = excluded.status,
                       current_task = excluded.current_task,
                       last_heartbeat = CURRENT_TIMESTAMP""",
                (self.agent_name, status, current_task),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Heartbeat: failed to update agent_heartbeat: {e}")

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        if self.on_heartbeat:
            return await self.on_heartbeat(HEARTBEAT_PROMPT)
        return None
