"""Nextcloud Talk channel — receives webhooks, forwards to OpenClaw Astrid, responds as Astrid user."""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import subprocess
import urllib.request
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class NextcloudTalkChannel(BaseChannel):
    """
    Nextcloud Talk channel — thin bridge to OpenClaw Astrid.

    Receives webhook POSTs from Nextcloud Talk, forwards messages to
    OpenClaw's chat completions endpoint on stacks, and posts Astrid's
    response back to Talk as the Astrid Nextcloud user.

    Config:
        enabled: bool
        server_url: str  — e.g. "http://superstation:8082"
        bot_secret: str  — shared secret from `occ talk:bot:install`
        port: int        — local port for webhook listener
        openclaw_url: str — e.g. "http://stacks:18789"
        openclaw_token: str — gateway auth token
        reply_as: str    — NC username to reply as (default: "Astrid")
    """

    name = "nextcloud_talk"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        self.server_url = getattr(config, "server_url", "").rstrip("/")
        self.bot_secret = getattr(config, "bot_secret", "")
        self.port = getattr(config, "port", 18793)
        self.openclaw_url = getattr(config, "openclaw_url", "").rstrip("/")
        self.openclaw_token = getattr(config, "openclaw_token", "")
        self.reply_as = getattr(config, "reply_as", "Astrid")
        self._fallback_api_key = ""  # Set from providers config if available
        self._nc_auth: str | None = None  # Basic auth header, fetched at start
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None

    def _load_fallback_api_key(self) -> None:
        """Load API key for local fallback from nanobot config."""
        config_path = os.path.expanduser("~/.nanobot-astrid/config.json")
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            self._fallback_api_key = cfg.get("providers", {}).get("anthropic", {}).get("api_key", "")
            if self._fallback_api_key:
                logger.info("NextcloudTalk: local fallback brain loaded (CLIProxyAPI)")
        except Exception:
            pass

    def _fetch_nc_app_password(self) -> str | None:
        """Fetch Nextcloud app password from Bitwarden for reply_as user."""
        secret_name = f"nextcloud-{self.reply_as.lower()}"
        try:
            result = subprocess.run(
                [os.path.expanduser("~/bin/bw-fetch-secret"), secret_name],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            logger.error(f"Failed to fetch {secret_name} from vault: {result.stderr.strip()}")
        except Exception as e:
            logger.error(f"Failed to fetch {secret_name} from vault: {e}")
        return None

    async def start(self) -> None:
        """Start the webhook HTTP server."""
        if not self.bot_secret:
            logger.error("NextcloudTalk: bot_secret not configured, cannot start")
            return

        # Load fallback API key from nanobot config
        self._load_fallback_api_key()

        # Fetch NC app password for the reply_as user
        nc_password = self._fetch_nc_app_password()
        if nc_password:
            creds = base64.b64encode(f"{self.reply_as}:{nc_password}".encode()).decode()
            self._nc_auth = f"Basic {creds}"
            logger.info(f"NextcloudTalk: will reply as NC user '{self.reply_as}'")
        else:
            logger.warning(f"NextcloudTalk: no NC password for '{self.reply_as}', falling back to Bot API")

        self._running = True
        self._app = web.Application()
        self._app.router.add_post("/nextcloud-talk-webhook", self._handle_webhook)
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await site.start()

        mode = "OpenClaw bridge" if self.openclaw_url else "local processing"
        logger.info(f"NextcloudTalk channel listening on port {self.port} ({mode})")

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the webhook server."""
        self._running = False
        if self._runner:
            await self._runner.cleanup()
        logger.info("NextcloudTalk channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Send a response to a Talk room as the Astrid user.

        Uses regular Chat API with Basic auth (appears as real user, not bot).
        Falls back to Bot API if no user credentials available.
        """
        token = msg.chat_id

        if self._nc_auth:
            # Post as the Astrid NC user — appears as a real participant
            url = f"{self.server_url}/ocs/v2.php/apps/spreed/api/v1/chat/{token}"
            body = json.dumps({"message": msg.content}).encode()

            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "OCS-APIRequest": "true",
                    "Authorization": self._nc_auth,
                },
                method="POST",
            )
        else:
            # Fallback: Bot API with HMAC signing
            url = f"{self.server_url}/ocs/v2.php/apps/spreed/api/v1/bot/{token}/message"
            body = json.dumps({"message": msg.content}).encode()

            random_val = os.urandom(32).hex()
            signature = hmac.new(
                self.bot_secret.encode(),
                (random_val + msg.content).encode(),
                hashlib.sha256,
            ).hexdigest()

            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "OCS-APIRequest": "true",
                    "X-Nextcloud-Talk-Bot-Random": random_val,
                    "X-Nextcloud-Talk-Bot-Signature": signature,
                },
                method="POST",
            )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                who = self.reply_as if self._nc_auth else "bot"
                logger.info(f"Talk response sent as {who} to room {token} (status {resp.status})")
        except urllib.error.HTTPError as e:
            body_resp = e.read().decode() if e.fp else ""
            logger.error(f"Failed to send Talk message to room {token}: {e} — {body_resp}")
        except Exception as e:
            logger.error(f"Failed to send Talk message to room {token}: {e}")

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """Handle incoming webhook from Nextcloud Talk."""
        raw_body = await request.read()

        # Verify HMAC signature
        # NC sends X-Nextcloud-Talk-Signature (not X-Nextcloud-Talk-Bot-Signature)
        sig_header = request.headers.get("X-Nextcloud-Talk-Signature", "")
        random_header = request.headers.get("X-Nextcloud-Talk-Random", "")

        if not self._verify_signature(random_header, raw_body, sig_header):
            logger.warning("NextcloudTalk: invalid webhook signature — rejecting")
            return web.json_response({"error": "Invalid signature"}, status=401)

        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "Invalid JSON"}, status=400)

        # Extract message details
        target = payload.get("target", {})
        room_token = target.get("id", "")
        actor = payload.get("actor", {})
        sender_id = actor.get("id", "unknown")
        sender_name = actor.get("name", "unknown")
        message_obj = payload.get("object", {})
        content = message_obj.get("content", "")

        if not room_token or not content:
            return web.json_response({"error": "Missing room token or content"}, status=400)

        # Ignore our own messages to prevent feedback loops
        actor_type = actor.get("type", "")
        if sender_id.lower() == f"users/{self.reply_as}".lower() or sender_name.lower() == self.reply_as.lower() or actor_type == "bots":
            logger.debug(f"Ignoring own message from {sender_name} in room {room_token}")
            return web.json_response({"status": "ignored (self)"})

        logger.info(f"Talk message from {sender_name} ({sender_id}) in room {room_token}")

        if self.openclaw_url and self.openclaw_token:
            # Option B: Forward to OpenClaw Astrid — one brain
            asyncio.create_task(self._forward_to_openclaw(
                sender_name=sender_name,
                sender_id=sender_id,
                room_token=room_token,
                content=content,
            ))
        else:
            # Fallback: local nanobot processing
            await self._handle_message(
                sender_id=sender_id,
                chat_id=room_token,
                content=content,
                metadata={
                    "sender_name": sender_name,
                    "room_token": room_token,
                    "source": "nextcloud_talk",
                },
            )

        return web.json_response({"status": "accepted"})

    def _call_chat_completions(self, url: str, headers: dict, body: bytes,
                               timeout: int = 120) -> str | None:
        """Call a chat completions endpoint. Returns reply text or None."""
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            reply = ""
            for choice in result.get("choices", []):
                msg = choice.get("message", {})
                if msg.get("content"):
                    reply += msg["content"]
            return reply or None
        except Exception as e:
            logger.warning(f"Chat completions call to {url} failed: {e}")
            return None

    async def _forward_to_openclaw(self, sender_name: str, sender_id: str,
                                    room_token: str, content: str) -> None:
        """Forward message to OpenClaw Astrid, fall back to local CLIProxyAPI."""
        user_msg = f"[Nextcloud Talk — {sender_name}] {content}"
        messages = [{"role": "user", "content": user_msg}]

        request_body = json.dumps({
            "model": "default",
            "messages": messages,
            "max_tokens": 4096,
        }).encode()

        # Try OpenClaw first (primary brain with full memory/context)
        reply = self._call_chat_completions(
            url=f"{self.openclaw_url}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openclaw_token}",
            },
            body=request_body,
            timeout=120,
        )
        source = "openclaw"

        # Fallback: local CLIProxyAPI (Claude via localhost:8317)
        if not reply:
            logger.warning(f"OpenClaw unavailable, falling back to local brain for room {room_token}")
            fallback_body = json.dumps({
                "model": "anthropic/claude-sonnet-4-6",
                "messages": [
                    {"role": "system", "content": (
                        "Du er Astrid, en AI-agent som jobber for IxoSynth. "
                        "Du svarer på norsk med mindre brukeren skriver på engelsk. "
                        "Vær vennlig, hjelpsom og konsis. "
                        "Merk: Du kjører i fallback-modus uten full hukommelse."
                    )},
                    *messages,
                ],
                "max_tokens": 4096,
            }).encode()

            api_key = getattr(self, '_fallback_api_key', '') or os.environ.get('ANTHROPIC_API_KEY', '')
            reply = self._call_chat_completions(
                url="http://localhost:8317/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                body=fallback_body,
                timeout=60,
            )
            source = "local-fallback"

        if not reply:
            logger.error(f"Both OpenClaw and local fallback failed for room {room_token}")
            return

        logger.info(f"{source} response for {room_token}: {len(reply)} chars")

        await self.send(OutboundMessage(
            channel="nextcloud_talk",
            chat_id=room_token,
            content=reply,
            metadata={"source": source},
        ))

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        mode = "openclaw-bridge" if self.openclaw_url else "local"
        return web.json_response({
            "status": "ok",
            "channel": "nextcloud_talk",
            "mode": mode,
            "openclaw": bool(self.openclaw_url),
        })

    def _verify_signature(self, random_val: str, body: bytes, signature: str) -> bool:
        """Verify the HMAC-SHA256 signature from Nextcloud Talk.

        Talk computes: HMAC-SHA256(secret, random + body)
        """
        if not signature or not random_val:
            return False

        expected = hmac.new(
            self.bot_secret.encode(),
            random_val.encode() + body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
