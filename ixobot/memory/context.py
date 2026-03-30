"""Build memory sections for agent system prompt injection."""

from ixobot.memory.store import PersistentMemoryStore


def build_memory_section(store: PersistentMemoryStore, max_crystals: int = 10, max_recent: int = 5) -> str:
    """Format crystals and recent memories as a system prompt section.

    Returns empty string if no memories exist.
    """
    crystals = store.get_crystals(limit=max_crystals)
    recent = store.query(limit=max_recent, importance_min=0.3)

    if not crystals and not recent:
        return ""

    parts = ["## Your Memory", "You have persistent memory across sessions.", ""]

    if crystals:
        parts.append("**Key insights (crystals):**")
        for c in crystals:
            parts.append(f"- {c['content']}")
        parts.append("")

    if recent:
        parts.append("**Recent observations:**")
        for m in recent:
            summary = m.get("summary") or m["content"]
            if len(summary) > 120:
                summary = summary[:117] + "..."
            parts.append(f"- {summary}")
        parts.append("")

    return "\n".join(parts)
