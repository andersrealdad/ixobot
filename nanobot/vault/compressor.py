"""Vault Engine — Compressor.

Receives RawObservation from the watcher queue, batches them over a time
window, then LLM-compresses each batch into StructuredMemory objects.

Pipeline: RawObservation → batch → LLM compress → StructuredMemory → router queue
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from nanobot.vault.config import (
    BATCH_WINDOW_SECONDS,
    LLM_MODEL,
    LLM_URL,
)
from nanobot.vault.watcher import RawObservation


@dataclass
class StructuredMemory:
    source_type: str
    source_id: str
    timestamp: datetime
    category: str        # decision | lesson | person | project | task | insight | pattern
    topic: str
    summary: str
    detail: dict = field(default_factory=dict)
    importance: int = 5  # 1-10
    agent_id: str | None = None
    tags: list[str] = field(default_factory=list)
    raw_observations: list[RawObservation] = field(default_factory=list)


COMPRESS_PROMPT = """You are Jimmy, the Vault Engine memory compressor.
Given a batch of raw observations from the agent system, compress each into a structured memory.

For EACH distinct event/topic, output a JSON object with:
- "category": one of "decision", "lesson", "person", "project", "task", "insight", "pattern"
- "topic": short topic label (2-5 words)
- "summary": one clear sentence capturing what happened and why it matters
- "importance": 1-10 (10 = critical architectural decision, 1 = routine heartbeat)
- "tags": list of relevant tags
- "source_ids": list of source_id strings this memory covers

Rules:
- Merge duplicate/related observations into ONE memory
- Heartbeats with no state change → skip (importance 0)
- Task completions → importance 5-7
- Architectural decisions or failures → importance 8-10
- Be concise. Summary should be one sentence.

Output a JSON array of objects. Nothing else.

Raw observations:
{observations}"""


class Compressor:
    """Batches RawObservations and LLM-compresses them into StructuredMemory."""

    def __init__(
        self,
        inbound: asyncio.Queue[RawObservation],
        outbound: asyncio.Queue[StructuredMemory],
        batch_window: int = BATCH_WINDOW_SECONDS,
    ):
        self.inbound = inbound
        self.outbound = outbound
        self.batch_window = batch_window

    async def run(self) -> None:
        """Main loop: collect batch → compress → emit."""
        logger.info(f"Compressor: starting (batch window {self.batch_window}s, model {LLM_MODEL})")
        while True:
            batch = await self._collect_batch()
            if not batch:
                continue
            try:
                memories = await self._compress(batch)
                for mem in memories:
                    await self.outbound.put(mem)
                logger.info(f"Compressor: {len(batch)} observations → {len(memories)} memories")
            except Exception as e:
                logger.error(f"Compressor: compression failed: {e}")
                # On failure, emit raw observations as minimal memories
                for obs in batch:
                    await self.outbound.put(self._fallback_memory(obs))

    async def _collect_batch(self) -> list[RawObservation]:
        """Collect observations for batch_window seconds, or until queue is idle."""
        batch: list[RawObservation] = []

        # Wait for at least one observation
        first = await self.inbound.get()
        batch.append(first)

        # Collect more until timeout
        deadline = asyncio.get_event_loop().time() + self.batch_window
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            try:
                obs = await asyncio.wait_for(self.inbound.get(), timeout=max(0.1, remaining))
                batch.append(obs)
            except asyncio.TimeoutError:
                break

        logger.debug(f"Compressor: collected batch of {len(batch)} observations")
        return batch

    async def _compress(self, batch: list[RawObservation]) -> list[StructuredMemory]:
        """Send batch to LLM for compression."""
        obs_text = "\n---\n".join(
            f"[{o.source_type}] {o.source_id} ({o.timestamp.isoformat()})\n"
            f"agent: {o.agent_id or 'system'}\n{o.content}"
            for o in batch
        )
        prompt = COMPRESS_PROMPT.format(observations=obs_text)

        raw_json = await self._call_llm(prompt)
        if not raw_json:
            return [self._fallback_memory(o) for o in batch]

        # Build source_id → observation lookup
        obs_by_id = {o.source_id: o for o in batch}

        memories: list[StructuredMemory] = []
        for item in raw_json:
            importance = item.get("importance", 5)
            if importance == 0:
                continue  # Skip routine noise

            source_ids = item.get("source_ids", [])
            raw_obs = [obs_by_id[sid] for sid in source_ids if sid in obs_by_id]

            mem = StructuredMemory(
                source_type=raw_obs[0].source_type if raw_obs else batch[0].source_type,
                source_id=source_ids[0] if source_ids else batch[0].source_id,
                timestamp=raw_obs[0].timestamp if raw_obs else batch[0].timestamp,
                category=item.get("category", "task"),
                topic=item.get("topic", "unknown"),
                summary=item.get("summary", ""),
                importance=min(10, max(1, importance)),
                tags=item.get("tags", []),
                agent_id=raw_obs[0].agent_id if raw_obs else None,
                raw_observations=raw_obs or batch[:1],
            )
            memories.append(mem)

        return memories

    async def _call_llm(self, prompt: str) -> list[dict[str, Any]] | None:
        """Call Ollama and parse JSON array response."""
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                resp = await client.post(
                    LLM_URL,
                    json={
                        "model": LLM_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1, "num_predict": 2048},
                    },
                )
                resp.raise_for_status()
                text = resp.json().get("response", "")
                # Ollama format: "json" wraps in object — try parse as array or extract
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, dict):
                    # LLMs wrap arrays in various keys
                    for key in ("memories", "data", "results", "observations"):
                        if key in parsed and isinstance(parsed[key], list):
                            return parsed[key]
                    # Single memory object → wrap
                    if "topic" in parsed or "summary" in parsed:
                        return [parsed]
                    logger.warning(f"Compressor: unexpected JSON structure: {list(parsed.keys())}")
                    return []
                return [parsed]
            except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
                logger.error(f"Compressor LLM call failed: {e}")
                return None

    @staticmethod
    def _fallback_memory(obs: RawObservation) -> StructuredMemory:
        """Create minimal memory from raw observation when LLM fails."""
        return StructuredMemory(
            source_type=obs.source_type,
            source_id=obs.source_id,
            timestamp=obs.timestamp,
            category="task",
            topic=obs.source_type,
            summary=obs.content[:200],
            importance=3,
            agent_id=obs.agent_id,
            tags=[obs.source_type],
            raw_observations=[obs],
        )
