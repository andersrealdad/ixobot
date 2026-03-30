"""MCP client — connects to stdio and SSE MCP servers."""

import asyncio
from contextlib import AsyncExitStack
from typing import Any

from loguru import logger

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client


class McpServer:
    """A single connected MCP server with its session and tools."""

    def __init__(self, name: str, session: ClientSession, tools: list[dict]):
        self.name = name
        self.session = session
        self.tools = tools  # raw tool defs from server

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on this MCP server."""
        result = await self.session.call_tool(tool_name, arguments)
        # Flatten content blocks into a single string
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts)


class McpClientManager:
    """Manages connections to multiple MCP servers.

    Config format (same as Claude Code):
    {
        "mcpServers": {
            "server-name": {
                "type": "stdio",          # or "sse"
                "command": "/path/to/bin",
                "args": ["--flag"],
                "env": {}                  # optional extra env vars
            }
        }
    }
    """

    def __init__(self):
        self._servers: dict[str, McpServer] = {}
        self._exit_stack = AsyncExitStack()

    async def connect_all(self, mcp_config: dict[str, dict]) -> None:
        """Connect to all configured MCP servers."""
        for name, cfg in mcp_config.items():
            try:
                await self._connect_one(name, cfg)
            except Exception as e:
                logger.error(f"MCP: failed to connect to '{name}': {e}")

    async def _connect_one(self, name: str, cfg: dict) -> None:
        """Connect to a single MCP server."""
        server_type = cfg.get("type", "stdio")

        if server_type == "stdio":
            command = cfg.get("command", "")
            args = cfg.get("args", [])
            env = cfg.get("env")
            if not command:
                logger.warning(f"MCP: '{name}' has no command, skipping")
                return

            params = StdioServerParameters(
                command=command,
                args=args,
                env=env,
            )
            transport = await self._exit_stack.enter_async_context(
                stdio_client(params)
            )

        elif server_type == "sse":
            url = cfg.get("url", "")
            if not url:
                logger.warning(f"MCP: '{name}' has no url, skipping")
                return

            transport = await self._exit_stack.enter_async_context(
                sse_client(url)
            )
        else:
            logger.warning(f"MCP: unknown type '{server_type}' for '{name}'")
            return

        read_stream, write_stream = transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        # List available tools
        tools_result = await session.list_tools()
        tools = [t.model_dump() for t in tools_result.tools]

        self._servers[name] = McpServer(name, session, tools)
        tool_names = [t["name"] for t in tools]
        logger.info(f"MCP: connected to '{name}' — {len(tools)} tools: {', '.join(tool_names[:5])}{'...' if len(tools) > 5 else ''}")

    async def disconnect_all(self) -> None:
        """Disconnect all MCP servers."""
        await self._exit_stack.aclose()
        self._servers.clear()

    def get_server(self, name: str) -> McpServer | None:
        """Get a connected server by name."""
        return self._servers.get(name)

    def get_server_for_tool(self, prefixed_name: str) -> tuple[McpServer, str] | None:
        """Resolve 'mcp__server__tool' to (server, tool_name)."""
        parts = prefixed_name.split("__", 2)
        if len(parts) != 3 or parts[0] != "mcp":
            return None
        server_name, tool_name = parts[1], parts[2]
        server = self._servers.get(server_name)
        if server:
            return server, tool_name
        return None

    @property
    def all_tools(self) -> list[tuple[str, str, dict]]:
        """Yield (server_name, tool_name, tool_def) for all connected servers."""
        result = []
        for server_name, server in self._servers.items():
            for tool in server.tools:
                result.append((server_name, tool["name"], tool))
        return result

    @property
    def connected_servers(self) -> list[str]:
        return list(self._servers.keys())
