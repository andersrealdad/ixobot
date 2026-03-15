"""Vault Engine — Watcher daemon.

Long-running asyncio service that tails all event sources and emits
RawObservation objects into an asyncio.Queue for downstream processing
(Observer/Compressor → Router/Scorer → vault.memories).

Event sources:
  - shared-memory.db: message_bus, task_queue, debate_utxo, agent_heartbeat, discussions
  - agent-homes/*/memory/MEMORY.md: file mtime polling
  - Gitea API: repo notifications (superfuru/*)

Runs as systemd unit: vault-watcher.service on superstation.
Registers heartbeat as agent_id='vault-watcher' in agent_heartbeat.

NEVER modifies source databases — read-only.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class RawObservation:
    source_type: str          # message_bus | task_queue | debate_utxo | heartbeat | memory_md | gitea
    source_id: str            # row id, file path, or event id
    timestamp: datetime
    content: str              # human-readable summary of the event
    metadata: dict = field(default_factory=dict)
    agent_id: str | None = None


# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_SHARED_MEMORY_DB = Path.home() / "shared-data" / "db" / "shared-memory.db"
DEFAULT_AGENT_HOMES = Path.home() / "DEV" / "operations" / "agent-homes"

POLL_INTERVAL_SQLITE = int(os.environ.get("VAULT_WATCHER_POLL_SQLITE", "30"))   # seconds
POLL_INTERVAL_FILES  = int(os.environ.get("VAULT_WATCHER_POLL_FILES",  "60"))
POLL_INTERVAL_GITEA  = int(os.environ.get("VAULT_WATCHER_POLL_GITEA",  "300"))
HEARTBEAT_INTERVAL   = int(os.environ.get("VAULT_WATCHER_HEARTBEAT",   "60"))


# ── Watcher ───────────────────────────────────────────────────────────────────

class VaultWatcher:
    """Fan-in watcher: one coroutine per source, shared output queue."""

    def __init__(
        self,
        queue: asyncio.Queue[RawObservation],
        shared_memory_db: Path | None = None,
        agent_homes: Path | None = None,
        gitea_url: str | None = None,
        gitea_token: str | None = None,
    ):
        self.queue = queue
        self._loop: asyncio.AbstractEventLoop | None = None
        self.db = shared_memory_db or DEFAULT_SHARED_MEMORY_DB
        self.agent_homes = agent_homes or DEFAULT_AGENT_HOMES
        self.gitea_url = gitea_url or os.environ.get("GITEA_URL", "http://ubsfuru:3001")
        self.gitea_token = gitea_token or os.environ.get("GITEA_TOKEN", "")

        # Watermarks: last seen id/mtime per source
        self._last_message_bus: int = 0
        self._last_task_queue: int = 0
        self._last_debate_utxo: int = 0
        self._last_heartbeat: int = 0
        self._last_discussion: int = 0
        self._file_mtimes: dict[str, float] = {}
        self._last_gitea_check: float = 0.0

    async def run(self) -> None:
        """Start all watchers concurrently. Runs until cancelled."""
        self._loop = asyncio.get_running_loop()
        logger.info("VaultWatcher: starting all source watchers")
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._watch_sqlite_loop(), name="sqlite-watcher")
            tg.create_task(self._watch_files_loop(), name="file-watcher")
            tg.create_task(self._watch_gitea_loop(), name="gitea-watcher")
            tg.create_task(self._heartbeat_loop(), name="heartbeat")

    # ── SQLite sources ────────────────────────────────────────────────────────

    async def _watch_sqlite_loop(self) -> None:
        while True:
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._poll_sqlite)
            except Exception as e:
                logger.warning(f"VaultWatcher sqlite poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL_SQLITE)

    def _poll_sqlite(self) -> None:
        if not self.db.exists():
            return
        conn = sqlite3.connect(str(self.db), timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            self._poll_message_bus(conn)
            self._poll_task_queue(conn)
            self._poll_debate_utxo(conn)
            self._poll_heartbeat(conn)
            self._poll_discussions(conn)
        finally:
            conn.close()

    def _emit(self, obs: RawObservation) -> None:
        """Thread-safe emit to asyncio queue."""
        self._loop.call_soon_threadsafe(self.queue.put_nowait, obs)

    def _poll_message_bus(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT id, from_agent, to_agent, channel, message, created_at "
            "FROM message_bus WHERE id > ? ORDER BY id ASC LIMIT 100",
            (self._last_message_bus,),
        ).fetchall()
        for r in rows:
            self._emit(RawObservation(
                source_type="message_bus",
                source_id=str(r["id"]),
                timestamp=_parse_ts(r["created_at"]),
                content=f"[{r['channel']}] {r['from_agent']} → {r['to_agent']}: {r['message'][:500]}",
                metadata={"from": r["from_agent"], "to": r["to_agent"], "channel": r["channel"]},
                agent_id=r["from_agent"],
            ))
            self._last_message_bus = max(self._last_message_bus, r["id"])
        if rows:
            logger.debug(f"VaultWatcher: {len(rows)} new message_bus rows")

    def _poll_task_queue(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT id, title, description, target_agent, status, result, updated_at "
            "FROM task_queue WHERE id > ? AND status IN ('done','failed') ORDER BY id ASC LIMIT 50",
            (self._last_task_queue,),
        ).fetchall()
        for r in rows:
            content = f"Task '{r['title']}' [{r['status']}] for {r['target_agent']}"
            if r["result"]:
                content += f"\nResult: {r['result'][:300]}"
            self._emit(RawObservation(
                source_type="task_queue",
                source_id=str(r["id"]),
                timestamp=_parse_ts(r["updated_at"]),
                content=content,
                metadata={"status": r["status"], "target_agent": r["target_agent"]},
                agent_id=r["target_agent"],
            ))
            self._last_task_queue = max(self._last_task_queue, r["id"])
        if rows:
            logger.debug(f"VaultWatcher: {len(rows)} completed task_queue rows")

    def _poll_debate_utxo(self, conn: sqlite3.Connection) -> None:
        try:
            rows = conn.execute(
                "SELECT id, topic, content, created_by, created_at "
                "FROM debate_utxo WHERE id > ? AND spent = 0 ORDER BY id ASC LIMIT 50",
                (self._last_debate_utxo,),
            ).fetchall()
        except sqlite3.OperationalError:
            return  # Table may not exist yet
        for r in rows:
            self._emit(RawObservation(
                source_type="debate_utxo",
                source_id=str(r["id"]),
                timestamp=_parse_ts(r["created_at"]),
                content=f"Debate [{r['topic']}]: {r['content'][:500]}",
                metadata={"topic": r["topic"], "created_by": r["created_by"]},
                agent_id=r["created_by"],
            ))
            self._last_debate_utxo = max(self._last_debate_utxo, r["id"])
        if rows:
            logger.debug(f"VaultWatcher: {len(rows)} new debate_utxo rows")

    def _poll_heartbeat(self, conn: sqlite3.Connection) -> None:
        try:
            rows = conn.execute(
                "SELECT rowid, agent_id, status, current_task, last_heartbeat "
                "FROM agent_heartbeat WHERE rowid > ? ORDER BY rowid ASC LIMIT 50",
                (self._last_heartbeat,),
            ).fetchall()
        except sqlite3.OperationalError:
            return
        for r in rows:
            if r["status"] in ("active", "error", "offline"):
                self._emit(RawObservation(
                    source_type="heartbeat",
                    source_id=f"{r['agent_id']}_{r['last_heartbeat']}",
                    timestamp=_parse_ts(r["last_heartbeat"]),
                    content=f"Agent {r['agent_id']} status: {r['status']}"
                            + (f" — {r['current_task']}" if r["current_task"] else ""),
                    metadata={"agent_id": r["agent_id"], "status": r["status"]},
                    agent_id=r["agent_id"],
                ))
            self._last_heartbeat = max(self._last_heartbeat, r["rowid"])

    def _poll_discussions(self, conn: sqlite3.Connection) -> None:
        try:
            rows = conn.execute(
                "SELECT id, title, proposal, status, updated_at "
                "FROM discussions WHERE id > ? AND status IN ('approved','rejected') "
                "ORDER BY id ASC LIMIT 20",
                (self._last_discussion,),
            ).fetchall()
        except sqlite3.OperationalError:
            return
        for r in rows:
            self._emit(RawObservation(
                source_type="debate_utxo",
                source_id=f"discussion_{r['id']}",
                timestamp=_parse_ts(r["updated_at"]),
                content=f"Discussion '{r['title']}' {r['status']}: {(r['proposal'] or '')[:400]}",
                metadata={"discussion_id": r["id"], "status": r["status"]},
            ))
            self._last_discussion = max(self._last_discussion, r["id"])
        if rows:
            logger.debug(f"VaultWatcher: {len(rows)} discussion verdicts")

    # ── File watcher ──────────────────────────────────────────────────────────

    async def _watch_files_loop(self) -> None:
        while True:
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._poll_memory_files)
            except Exception as e:
                logger.warning(f"VaultWatcher file poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL_FILES)

    def _poll_memory_files(self) -> None:
        if not self.agent_homes.exists():
            return
        for memory_file in self.agent_homes.glob("*/memory/MEMORY.md"):
            path_str = str(memory_file)
            try:
                mtime = memory_file.stat().st_mtime
            except OSError:
                continue
            last = self._file_mtimes.get(path_str, 0.0)
            if mtime > last and last > 0:
                agent_id = memory_file.parent.parent.name
                content = _read_tail(memory_file, chars=1000)
                self._emit(RawObservation(
                    source_type="memory_md",
                    source_id=path_str,
                    timestamp=datetime.fromtimestamp(mtime),
                    content=f"MEMORY.md updated for agent '{agent_id}':\n{content}",
                    metadata={"file": path_str, "agent_id": agent_id},
                    agent_id=agent_id,
                ))
                logger.debug(f"VaultWatcher: MEMORY.md changed for {agent_id}")
            self._file_mtimes[path_str] = mtime

    # ── Gitea watcher ─────────────────────────────────────────────────────────

    async def _watch_gitea_loop(self) -> None:
        while True:
            try:
                await self._poll_gitea()
            except Exception as e:
                logger.debug(f"VaultWatcher gitea poll error: {e}")
            await asyncio.sleep(POLL_INTERVAL_GITEA)

    async def _poll_gitea(self) -> None:
        if not self.gitea_token:
            return
        try:
            import httpx
        except ImportError:
            return

        since = self._last_gitea_check
        self._last_gitea_check = time.time()
        if since == 0:
            return  # Skip first tick — avoid flood on startup

        headers = {"Authorization": f"token {self.gitea_token}"}
        repos = ["operations", "intent", "atlas", "garage", "IXO-Synth", "ixonaut"]
        async with httpx.AsyncClient(timeout=10) as client:
            for repo in repos:
                try:
                    resp = await client.get(
                        f"{self.gitea_url}/api/v1/repos/superfuru/{repo}/issues",
                        headers=headers,
                        params={"state": "closed", "limit": 10, "type": "issues"},
                    )
                    if resp.status_code != 200:
                        continue
                    for issue in resp.json():
                        closed_at = issue.get("closed_at") or ""
                        if not closed_at:
                            continue
                        closed_ts = _parse_ts(closed_at).timestamp()
                        if closed_ts > since:
                            self._emit(RawObservation(
                                source_type="gitea",
                                source_id=f"{repo}#{issue['number']}",
                                timestamp=_parse_ts(closed_at),
                                content=f"Gitea issue closed: [{repo}#{issue['number']}] {issue['title']}",
                                metadata={"repo": repo, "issue": issue["number"], "title": issue["title"]},
                            ))
                except Exception as e:
                    logger.debug(f"VaultWatcher gitea {repo}: {e}")

    # ── Heartbeat registration ────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await asyncio.get_running_loop().run_in_executor(None, self._register_heartbeat)
            except Exception as e:
                logger.debug(f"VaultWatcher heartbeat error: {e}")
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    def _register_heartbeat(self) -> None:
        if not self.db.exists():
            return
        try:
            conn = sqlite3.connect(str(self.db), timeout=5)
            conn.execute(
                """INSERT INTO agent_heartbeat (agent_id, agent_type, status, last_heartbeat, started_at)
                   VALUES ('vault-watcher', 'service', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                   ON CONFLICT(agent_id) DO UPDATE SET
                       status = 'active',
                       last_heartbeat = CURRENT_TIMESTAMP""",
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"VaultWatcher: heartbeat registration failed: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_ts(value: Any) -> datetime:
    """Parse timestamp string or return now() on failure."""
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.now()
    try:
        from dateutil import parser as dp
        return dp.parse(str(value))
    except Exception:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return datetime.now()


def _read_tail(path: Path, chars: int = 1000) -> str:
    """Read last N chars of a file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[-chars:] if len(text) > chars else text
    except OSError:
        return ""


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    """Run VaultWatcher standalone — pipe observations to stdout for debugging."""
    import sys

    queue: asyncio.Queue[RawObservation] = asyncio.Queue()

    # Resolve Gitea token from vault
    gitea_token = ""
    try:
        sys.path.insert(0, str(Path.home() / "DEV" / "garage" / "infra" / "bw-serve"))
        from secrets_client import get_secret
        gitea_token = get_secret("claude-code")
    except Exception:
        pass

    watcher = VaultWatcher(queue=queue, gitea_token=gitea_token)

    async def drain() -> None:
        while True:
            obs = await queue.get()
            logger.info(f"[{obs.source_type}] {obs.source_id}: {obs.content[:120]}")

    async with asyncio.TaskGroup() as tg:
        tg.create_task(watcher.run(), name="watcher")
        tg.create_task(drain(), name="drain")


if __name__ == "__main__":
    import sys
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")
    asyncio.run(main())
