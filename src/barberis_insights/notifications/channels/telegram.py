"""Telegram Bot API (https://core.telegram.org/bots/api). Messages are HTML and at most 4096 characters; longer ones are split on line breaks."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from . import ChannelError

LIMIT = 4096


def split(text: str, limit: int = LIMIT) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            parts.append(cur); cur = ""
        while len(line) > limit:                     # a single enormous line
            parts.append(line[:limit]); line = line[limit:]
        cur = f"{cur}\n{line}" if cur else line
    return parts + ([cur] if cur else [])


class TelegramChannel:
    name = "telegram"

    def __init__(self, token: str, timeout: int = 15):
        self.token, self.timeout = token, timeout

    def _call(self, method: str, payload: dict | None = None) -> dict:
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/{method}", data=json.dumps(payload or {}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = json.loads(e.read() or b"{}")
        except (urllib.error.URLError, TimeoutError) as e:
            raise ChannelError(f"Telegram unreachable: {e}") from None
        if not body.get("ok"):
            raise ChannelError(f"Telegram error: {body.get('description', 'unknown')}")   # never includes the token
        return body["result"]

    def send(self, recipient, text: str) -> str:
        if not recipient.telegram_chat_id:
            raise ChannelError(f"{recipient.name} has no Telegram chat id yet: press Start in the bot")
        ids = [str(self._call("sendMessage", {"chat_id": recipient.telegram_chat_id, "text": part, "parse_mode": "HTML",
                                              "disable_web_page_preview": True})["message_id"]) for part in split(text)]
        return ",".join(ids)[:40]

    def updates(self) -> list[dict]:
        """Chats that have written to the bot (to find a chat id after pressing Start)."""
        return self._call("getUpdates")
