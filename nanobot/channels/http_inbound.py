"""HTTP Inbound channel — simple webhook receiver for Router dispatch.

Listens on a configurable port for POST /inbound requests from the
atlas Router (or any HTTP client). Messages are forwarded through the
nanobot message bus for agent processing. Responses are returned
synchronously in the HTTP response.

Config:
    enabled: bool
    port: int — local port for the HTTP server (default 9881)
"""

import asyncio
import json
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class HttpInboundChannel(BaseChannel):
    """
    Minimal HTTP channel that receives JSON POST requests and feeds
    them into the nanobot agent loop.

    Expected POST body:
        {
            "channel": "gitea",
            "chat_id": "repo#issue",
            "content": "message text",
            "metadata": { ... }
        }

    The agent's response is collected from the outbound bus and
    returned in the HTTP response.
    """

    name = "http_inbound"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        self.port = getattr(config, "port", 9881)
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._pending: dict[str, asyncio.Future] = {}

    async def start(self) -> None:
        """Start the HTTP inbound server."""
        self._running = True
        self._app = web.Application()
        self._app.router.add_post("/inbound", self._handle_inbound)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()

        logger.info(f"HTTP Inbound channel listening on port {self.port}")

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the HTTP server."""
        self._running = False
        if self._runner:
            await self._runner.cleanup()
        logger.info("HTTP Inbound channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Route outbound message to pending HTTP response."""
        key = msg.chat_id
        if key in self._pending and not self._pending[key].done():
            self._pending[key].set_result(msg.content)
        else:
            logger.debug(f"No pending request for chat_id={key}, dropping outbound")

    async def _handle_inbound(self, request: web.Request) -> web.Response:
        """Handle POST /inbound from the Router."""
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON"}, status=400)

        content = payload.get("content", "")
        chat_id = payload.get("chat_id", "unknown")
        channel = payload.get("channel", "http_inbound")
        metadata = payload.get("metadata", {})

        if not content:
            return web.json_response({"error": "Missing content"}, status=400)

        logger.info(f"Inbound from {channel}: chat_id={chat_id}, {len(content)} chars")

        # Create a future for the response
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[chat_id] = future

        # Push message into the agent loop
        await self._handle_message(
            sender_id=metadata.get("comment_author", "router"),
            chat_id=chat_id,
            content=content,
            metadata=metadata,
        )

        # Wait for the agent to respond (timeout 120s)
        try:
            response = await asyncio.wait_for(future, timeout=120)
            return web.json_response({"status": "ok", "response": response})
        except asyncio.TimeoutError:
            logger.warning(f"Timeout waiting for agent response on chat_id={chat_id}")
            return web.json_response({"status": "timeout"}, status=504)
        finally:
            self._pending.pop(chat_id, None)

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "ok",
            "channel": "http_inbound",
            "port": self.port,
        })
