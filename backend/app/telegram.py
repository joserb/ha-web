"""Bounded Telegram sender. Never log URLs, tokens or provider response bodies."""
import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SendResult:
    status: str
    detail: str | None = None
    retry_after: float | None = None


class TelegramSender:
    def __init__(self, token: str, chat_id: str, timezone: str = "Europe/Madrid"):
        self.token = token.strip()
        self.chat_id = chat_id.strip()
        self.timezone = ZoneInfo(timezone)

    @property
    def configured(self):
        return bool(self.token and self.chat_id)

    async def send(self, delivery: dict) -> SendResult:
        return await asyncio.to_thread(self._send, delivery)

    def _send(self, delivery: dict) -> SendResult:
        if not self.configured:
            return SendResult("failed", "Telegram is not configured")
        when = datetime.fromtimestamp(delivery["timestamp"], self.timezone)
        message = f"🚪 {delivery['label']}: puerta abierta · {when:%d/%m/%Y %H:%M:%S} ({self.timezone.key})"
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            data=json.dumps({"chat_id": self.chat_id, "text": message}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                body = json.load(response)
            if body.get("ok"):
                return SendResult("sent")
            code = body.get("error_code", 0)
        except urllib.error.HTTPError as exc:
            code = exc.code
            try:
                body = json.loads(exc.read(16384))
            except (ValueError, OSError):
                body = {}
        except Exception:
            # Even a connection timeout may occur AFTER acceptance. Prefer no duplicates.
            return SendResult("delivery_unknown", "Delivery could not be confirmed; not retried")
        if code == 429:
            delay = body.get("parameters", {}).get("retry_after", 30)
            return SendResult("failed", "Telegram rate limit", float(delay) if isinstance(delay, (int, float)) else 30)
        if isinstance(code, int) and 500 <= code < 600:
            return SendResult("failed", "Telegram temporarily unavailable", 5)
        return SendResult("failed", "Telegram rejected the message; check bot and chat configuration")
