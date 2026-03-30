"""FLASH tool — broadcast a message to all Matrix rooms."""

from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool


class FlashTool(Tool):
    """Broadcast an urgent message to all or specific Matrix rooms."""

    name = "flash"
    description = (
        "Send a FLASH broadcast to Matrix rooms. Use for urgent alerts, "
        "pipeline failures, status updates, or coordination messages. "
        "Sends to all rooms by default, or specify target rooms."
    )
    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message to broadcast. Will be prefixed with ⚡ FLASH.",
            },
            "rooms": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of room aliases to target: "
                    "'kitchen-table', 'ops', 'shadow-chamber'. "
                    "Empty = all joined rooms."
                ),
            },
            "severity": {
                "type": "string",
                "enum": ["info", "warning", "critical"],
                "description": "Severity level. Default: info.",
            },
        },
        "required": ["message"],
    }

    def __init__(self, homeserver: str = "", access_token: str = ""):
        self._homeserver = homeserver
        self._access_token = access_token

    async def execute(self, **kwargs: Any) -> str:
        message = kwargs["message"]
        severity = kwargs.get("severity", "info")
        target_rooms = kwargs.get("rooms", [])

        if not self._homeserver or not self._access_token:
            return "FLASH failed: Matrix not configured"

        prefix = {"info": "⚡", "warning": "⚠️", "critical": "🚨"}
        flash_msg = f"{prefix.get(severity, '⚡')} **FLASH** — {message}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get joined rooms
            resp = await client.get(
                f"{self._homeserver}/_matrix/client/v3/joined_rooms",
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
            if resp.status_code != 200:
                return f"FLASH failed: could not get rooms ({resp.status_code})"

            joined = resp.json().get("joined_rooms", [])

            # Filter by alias if specified
            if target_rooms:
                # Resolve aliases to room IDs
                target_ids = set()
                for alias in target_rooms:
                    # Try with and without # prefix
                    full_alias = alias if alias.startswith("#") else f"#{alias}"
                    if ":" not in full_alias:
                        full_alias += f":matrix.ixobot.com"
                    try:
                        r = await client.get(
                            f"{self._homeserver}/_matrix/client/v3/directory/room/{full_alias}",
                            headers={"Authorization": f"Bearer {self._access_token}"},
                        )
                        if r.status_code == 200:
                            target_ids.add(r.json()["room_id"])
                    except Exception:
                        pass
                joined = [r for r in joined if r in target_ids]

            # Send to each room
            import uuid
            sent = 0
            for room_id in joined:
                try:
                    txn_id = str(uuid.uuid4())
                    await client.put(
                        f"{self._homeserver}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn_id}",
                        headers={"Authorization": f"Bearer {self._access_token}"},
                        json={"msgtype": "m.text", "body": flash_msg},
                    )
                    sent += 1
                except Exception as e:
                    logger.warning(f"FLASH failed for {room_id}: {e}")

        return f"FLASH sent to {sent}/{len(joined)} rooms: {message[:80]}"
