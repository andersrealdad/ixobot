"""Memory system for persistent agent memory."""

import os
from pathlib import Path
from datetime import datetime

from loguru import logger

from nanobot.utils.helpers import ensure_dir, today_date


class MemoryStore:
    """
    Memory system for the agent.

    Supports daily notes (memory/YYYY-MM-DD.md), long-term memory (MEMORY.md),
    and Open Brain semantic recall (pgvector on PostgreSQL).
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.agent_name = os.environ.get("NANOBOT_AGENT_NAME")
    
    def get_today_file(self) -> Path:
        """Get path to today's memory file."""
        return self.memory_dir / f"{today_date()}.md"
    
    def read_today(self) -> str:
        """Read today's memory notes."""
        today_file = self.get_today_file()
        if today_file.exists():
            return today_file.read_text(encoding="utf-8")
        return ""
    
    def append_today(self, content: str) -> None:
        """Append content to today's memory notes."""
        today_file = self.get_today_file()
        
        if today_file.exists():
            existing = today_file.read_text(encoding="utf-8")
            content = existing + "\n" + content
        else:
            # Add header for new day
            header = f"# {today_date()}\n\n"
            content = header + content
        
        today_file.write_text(content, encoding="utf-8")
    
    def read_long_term(self) -> str:
        """Read long-term memory (MEMORY.md)."""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""
    
    def write_long_term(self, content: str) -> None:
        """Write to long-term memory (MEMORY.md)."""
        self.memory_file.write_text(content, encoding="utf-8")
    
    def get_recent_memories(self, days: int = 7) -> str:
        """
        Get memories from the last N days.
        
        Args:
            days: Number of days to look back.
        
        Returns:
            Combined memory content.
        """
        from datetime import timedelta
        
        memories = []
        today = datetime.now().date()
        
        for i in range(days):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            file_path = self.memory_dir / f"{date_str}.md"
            
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                memories.append(content)
        
        return "\n\n---\n\n".join(memories)
    
    def list_memory_files(self) -> list[Path]:
        """List all memory files sorted by date (newest first)."""
        if not self.memory_dir.exists():
            return []
        
        files = list(self.memory_dir.glob("????-??-??.md"))
        return sorted(files, reverse=True)
    
    def get_brain_context(self) -> str:
        """Query Open Brain for this agent's most relevant collective knowledge.

        Returns formatted insights (decisions, lessons, observations) from all
        agents. Excludes task_result type to avoid overlap with heartbeat
        context injection. Fails silently if Open Brain is unavailable.
        """
        try:
            from nanobot.heartbeat.open_brain import search_context, ENABLED
            if not ENABLED:
                return ""
        except ImportError:
            return ""

        # Build a domain query from SOUL.md or agent name
        soul_path = self.workspace / "SOUL.md"
        if soul_path.exists():
            try:
                soul = soul_path.read_text(encoding="utf-8")[:500]
                query = f"Agent {self.agent_name or 'nanobot'}: {soul}"
            except Exception:
                query = f"important decisions and lessons for agent {self.agent_name or 'nanobot'}"
        else:
            query = f"important decisions and lessons for agent {self.agent_name or 'nanobot'}"

        context = search_context(query, self.agent_name)
        if not context:
            return ""

        # Replace the heartbeat-style header with a brain-specific one
        context = context.replace(
            "## Prior Knowledge (from Open Brain)",
            "## Open Brain — Collective Intelligence",
        )
        return context

    def get_memory_context(self) -> str:
        """
        Get memory context for the agent.

        Returns:
            Formatted memory context including long-term memory, recent notes,
            and Open Brain semantic recall.
        """
        parts = []

        # Long-term memory
        long_term = self.read_long_term()
        if long_term:
            parts.append("## Long-term Memory\n" + long_term)

        # Today's notes
        today = self.read_today()
        if today:
            parts.append("## Today's Notes\n" + today)

        # Open Brain — collective intelligence from all agents
        brain = self.get_brain_context()
        if brain:
            parts.append(brain)

        return "\n\n".join(parts) if parts else ""
