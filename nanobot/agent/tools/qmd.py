"""QMD hybrid search tool — invokes the QMD CLI for knowledge search."""

import asyncio
import shutil
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool


class QmdSearchTool(Tool):
    """Search the knowledge base via QMD (BM25 + vector + LLM rerank)."""

    def __init__(self):
        self._qmd_path = shutil.which("qmd")
        if not self._qmd_path:
            logger.warning("qmd not found on PATH — qmd_search tool will return errors if invoked")

    @property
    def name(self) -> str:
        return "qmd_search"

    @property
    def description(self) -> str:
        return (
            "Search the knowledge base using hybrid retrieval (BM25 + vector + LLM rerank). "
            "Returns relevant file snippets with source paths and relevance scores."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                },
                "collection": {
                    "type": "string",
                    "description": "Limit to a specific collection. Omit to search all indexed collections.",
                },
                "deep": {
                    "type": "boolean",
                    "description": "If true, use deep_search with query expansion + reranking (~10s). Default false uses keyword search (~30ms).",
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, collection: str | None = None, deep: bool = False, **kwargs: Any) -> str:
        """Execute a QMD search via CLI subprocess."""
        if not self._qmd_path:
            return "Error: qmd not found on PATH. Install with: npm install -g @nicolo-ribaudo/qmd"

        cmd = [self._qmd_path]
        if deep:
            cmd.append("query")  # deep_search with reranking
        else:
            cmd.append("search")  # fast BM25 keyword search

        cmd.append(query)

        if collection:
            cmd.extend(["--collection", collection])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            return "Error: QMD search timed out"
        except Exception as e:
            return f"Error running QMD: {e}"

        output = stdout.decode().strip()
        if not output:
            error = stderr.decode().strip()
            if error:
                return f"QMD error: {error}"
            return "No results found."

        return output
