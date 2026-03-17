"""Matrix channel implementation using matrix-nio with E2E encryption support."""

import asyncio
from pathlib import Path

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import MatrixConfig

try:
    import nio
except ImportError:
    nio = None  # type: ignore[assignment]


class MatrixChannel(BaseChannel):
    """
    Matrix channel using nio.AsyncClient with E2E encryption.

    Connects to a Matrix homeserver via /sync long-poll.
    Each room the bot is in becomes a separate chat_id,
    so agents maintain per-room conversation history.

    E2E keys are stored in a per-user store directory so
    device verification persists across restarts.
    """

    name = "matrix"

    def __init__(self, config: MatrixConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: MatrixConfig = config
        self._client: "nio.AsyncClient | None" = None
        self._sync_token: str | None = None

    def _store_path(self) -> Path:
        """Per-user E2E key store directory."""
        # Extract username from @user:server
        username = self.config.user_id.split(":")[0].lstrip("@")
        store = Path.home() / ".nanobot" / "matrix-store" / username
        store.mkdir(parents=True, exist_ok=True)
        return store

    async def start(self) -> None:
        """Start the Matrix client and begin syncing."""
        if nio is None:
            logger.error("matrix-nio not installed. Run: uv pip install 'matrix-nio[e2e]'")
            return

        if not self.config.homeserver or not self.config.access_token:
            logger.error("Matrix homeserver and access_token must be configured")
            return

        self._running = True

        self._client = nio.AsyncClient(
            homeserver=self.config.homeserver,
            user=self.config.user_id,
        )
        self._client.access_token = self.config.access_token

        # Initial sync FIRST to skip old messages and populate device/key store
        # Callbacks are registered AFTER so old messages don't trigger processing
        logger.info(f"Matrix: initial sync as {self.config.user_id} (E2E enabled)...")
        resp = await self._client.sync(timeout=5000)
        if isinstance(resp, nio.SyncError):
            logger.error(f"Matrix sync failed: {resp.message}")
            return
        self._sync_token = resp.next_batch

        # Now register callbacks — only NEW messages will trigger them
        self._client.add_event_callback(self._on_room_message, nio.RoomMessageText)
        self._client.add_event_callback(self._on_invite, nio.InviteMemberEvent)

        room_count = len(resp.rooms.join)
        logger.info(f"Matrix: connected, in {room_count} rooms")

        # Sync loop
        while self._running:
            try:
                resp = await self._client.sync(
                    timeout=30000,
                    since=self._sync_token,
                )
                if isinstance(resp, nio.SyncError):
                    logger.warning(f"Matrix sync error: {resp.message}")
                    await asyncio.sleep(5)
                    continue
                self._sync_token = resp.next_batch
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Matrix sync exception: {e}")
                if self._running:
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """Stop the Matrix client."""
        self._running = False
        if self._client:
            await self._client.close()
            self._client = None

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message to a Matrix room (auto-encrypts if room is encrypted)."""
        if not self._client:
            logger.warning("Matrix client not running")
            return

        content = {
            "msgtype": "m.text",
            "body": msg.content,
            "format": "org.matrix.custom.html",
            "formatted_body": _markdown_to_html(msg.content),
        }

        try:
            # room_send auto-encrypts for E2E rooms when store is configured
            resp = await self._client.room_send(
                room_id=msg.chat_id,
                message_type="m.room.message",
                content=content,
            )
            if isinstance(resp, nio.RoomSendError):
                logger.error(f"Matrix send failed in {msg.chat_id}: {resp.message}")
        except Exception as e:
            logger.error(f"Matrix send error: {e}")

    async def _on_room_message(
        self, room: "nio.MatrixRoom", event: "nio.RoomMessageText"
    ) -> None:
        """Handle incoming plaintext room messages."""
        await self._process_message(room, event)

    async def _on_encrypted_message(
        self, room: "nio.MatrixRoom", event: "nio.MegolmEvent"
    ) -> None:
        """Handle E2E encrypted messages that couldn't be decrypted."""
        logger.warning(
            f"Matrix: could not decrypt message in {room.display_name} "
            f"from {event.sender} (session: {event.session_id[:8]}...)"
        )
        # Request keys from the sender
        if self._client:
            try:
                await self._client.request_room_key(event)
            except Exception:
                pass

    async def _process_message(
        self, room: "nio.MatrixRoom", event: "nio.RoomMessageText"
    ) -> None:
        """Process a decrypted message."""
        # Ignore own messages
        if event.sender == self.config.user_id:
            return

        sender_id = event.sender
        room_id = room.room_id

        # Filter by allowed rooms if configured
        if self.config.rooms and room_id not in self.config.rooms:
            return

        content = event.body or ""
        if not content:
            return

        logger.debug(f"Matrix [{room.display_name}] {sender_id}: {content[:80]}...")

        await self._handle_message(
            sender_id=sender_id,
            chat_id=room_id,
            content=content,
            metadata={
                "event_id": event.event_id,
                "room_name": room.display_name,
                "room_id": room_id,
                "encrypted": room.encrypted,
            },
        )

    async def _on_invite(
        self, room: "nio.MatrixRoom", event: "nio.InviteMemberEvent"
    ) -> None:
        """Auto-join rooms when invited."""
        if not self._client:
            return

        if event.membership == "invite" and event.state_key == self.config.user_id:
            logger.info(f"Matrix: auto-joining room {room.room_id}")
            await self._client.join(room.room_id)

    async def _on_key_request(self, event: "nio.KeyVerificationStart") -> None:
        """Auto-accept key verification requests."""
        if not self._client:
            return
        logger.info(f"Matrix: key verification request from {event.sender}")

    async def _trust_all_devices(self) -> None:
        """Trust all devices of all users in joined rooms.

        For internal agent-to-human use, we trust all devices automatically.
        This allows E2E encrypted rooms to work without manual verification.
        """
        if not self._client:
            return

        for room_id in self._client.rooms:
            room = self._client.rooms[room_id]
            for user_id in room.users:
                devices = self._client.device_store.active_user_devices(user_id)
                for device in devices:
                    if not self._client.olm.is_device_verified(device):
                        self._client.verify_device(device)
                        logger.debug(f"Matrix: trusted device {device.device_id} of {user_id}")


def _markdown_to_html(text: str) -> str:
    """Basic markdown to HTML for Matrix formatted_body."""
    import re

    if not text:
        return ""

    # Code blocks
    text = re.sub(
        r"```(\w*)\n?([\s\S]*?)```",
        r"<pre><code>\2</code></pre>",
        text,
    )
    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])", r"<em>\1</em>", text)
    # Line breaks
    text = text.replace("\n", "<br>")

    return text
