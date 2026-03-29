"""Abstract base for IxoBot persistent memory backends."""

from abc import ABC, abstractmethod
from typing import Optional


class PersistentMemoryStore(ABC):
    """Contract for persistent memory backends (SQLite, PostgreSQL, etc.)."""

    @abstractmethod
    def store(self, memory: dict) -> str:
        """Store a memory dict. Required keys: content, memory_type.
        Optional: summary, importance, source, agent_name, metadata.
        Returns the memory ID."""

    @abstractmethod
    def query(
        self,
        limit: int = 20,
        importance_min: float = 0.0,
        memory_type: Optional[str] = None,
    ) -> list[dict]:
        """Query memories ordered by recency. Filter by importance and type."""

    @abstractmethod
    def promote(self, memory_id: str, crystal: dict) -> None:
        """Promote a memory to a crystal. crystal dict has: content, topics."""

    @abstractmethod
    def get_crystals(self, limit: int = 10) -> list[dict]:
        """Get crystals ordered by recency."""

    @abstractmethod
    def decay(self, rate: float = 0.01) -> int:
        """Reduce decay_score on unpromoted memories. Returns count affected."""
