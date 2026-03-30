"""MCP → nanobot Tool bridge.

Each MCP tool becomes a nanobot Tool so the agent can discover and call it
through the standard tool registry. Names are prefixed: mcp__{server}__{tool}.

Tool filtering: if skill nodes in Obsidian define a `tools:` list,
only those tools are registered. Otherwise all tools from the server are loaded.
"""

from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.mcp.client import McpClientManager


class McpTool(Tool):
    """Wraps a single MCP server tool as a nanobot Tool."""

    def __init__(self, server_name: str, tool_name: str, tool_def: dict, manager: McpClientManager):
        self._server_name = server_name
        self._tool_name = tool_name
        self._tool_def = tool_def
        self._manager = manager

    @property
    def name(self) -> str:
        return f"mcp__{self._server_name}__{self._tool_name}"

    @property
    def description(self) -> str:
        return self._tool_def.get("description", f"MCP tool: {self._tool_name}")

    @property
    def parameters(self) -> dict[str, Any]:
        return self._tool_def.get("inputSchema", {"type": "object", "properties": {}})

    async def execute(self, **kwargs: Any) -> str:
        server = self._manager.get_server(self._server_name)
        if not server:
            return f"Error: MCP server '{self._server_name}' not connected"
        try:
            return await server.call_tool(self._tool_name, kwargs)
        except Exception as e:
            return f"Error calling {self._server_name}/{self._tool_name}: {e}"


def _load_skill_tool_filters(vault_path: Path | None = None) -> dict[str, set[str]]:
    """Load tool filters from Obsidian skill nodes.

    Returns a dict mapping MCP server name → set of allowed tool names.
    If a server has no skill node or no `tools:` field, it's not in the dict
    (meaning: allow all tools from that server).
    """
    from nanobot.mcp.linker import discover_skills

    filters: dict[str, set[str]] = {}
    skills = discover_skills(vault_path)

    for skill_id, data in skills.items():
        tools_list = data.get("tools", [])
        if not tools_list:
            continue
        for server_name in data.get("mcp-servers", []):
            if server_name not in filters:
                filters[server_name] = set()
            filters[server_name].update(tools_list)

    return filters


def register_mcp_tools(
    manager: McpClientManager,
    registry: ToolRegistry,
    vault_path: Path | None = None,
) -> int:
    """Register MCP tools into the nanobot tool registry.

    Skill-scoped: if an Obsidian skill node defines a `tools:` list for a server,
    only those tools are registered. Servers without a skill node get all tools.

    Returns the number of tools registered.
    """
    filters = _load_skill_tool_filters(vault_path)

    count = 0
    skipped = 0
    for server_name, tool_name, tool_def in manager.all_tools:
        # Filter: if this server has a skill-defined allowlist, check it
        if server_name in filters and tool_name not in filters[server_name]:
            skipped += 1
            continue

        mcp_tool = McpTool(server_name, tool_name, tool_def, manager)
        registry.register(mcp_tool)
        count += 1

    if count:
        msg = f"MCP bridge: registered {count} tools from {len(manager.connected_servers)} server(s)"
        if skipped:
            msg += f" ({skipped} filtered by skill nodes)"
        logger.info(msg)

    return count
