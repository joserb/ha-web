"""Transiciones de la puerta que merecen un análisis.

Aplica las mismas garantías que los avisos de Telegram del backend
(`backend/app/notification_rules.py`): la misma lectura llega por el topic
individual y por el agregado, la reconexión reproduce retenidos y un evento
viejo no tiene vídeo que analizar. Solo cuenta un cambio de estado nuevo, no
retenido, reciente y observado después de tener línea base.
"""
import json
from datetime import datetime, timezone

MAX_EVENT_AGE = 120
FUTURE_TOLERANCE = 5
STATES = {"open", "closed"}


def parse_timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def door_reading(topic: str, payload: str, device: str) -> tuple[str, float] | None:
    """(estado, timestamp de origen) de la puerta en un mensaje de `/ZRO/env/#`."""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if topic == "/ZRO/env/state":
        devices = data.get("devices")
        data = devices.get(device) if isinstance(devices, dict) else None
    elif topic != f"/ZRO/env/{device}":
        return None
    if not isinstance(data, dict) or data.get("type") != "contact":
        return None
    state, updated_at = data.get("state"), data.get("updated_at")
    if not isinstance(state, str) or not isinstance(updated_at, str):
        return None
    try:
        return state.lower(), parse_timestamp(updated_at)
    except ValueError:
        return None


class DoorWatcher:
    def __init__(self, max_age: float = MAX_EVENT_AGE):
        self.max_age = max_age
        self.state: str | None = None
        self.timestamp: float | None = None
        self.baselined = False

    def reset(self):
        """Tras reconectar, la primera lectura solo vuelve a fijar la línea base."""
        self.baselined = False

    def observe(self, state: str, timestamp: float, retained: bool, now: float) -> str | None:
        """Devuelve `open` o `closed` si la lectura es una transición real."""
        if state not in STATES or timestamp > now + FUTURE_TOLERANCE:
            return None
        if self.timestamp is not None and timestamp <= self.timestamp:
            # La copia repetida (agregado, retenido) confirma lo que ya se sabía.
            if timestamp == self.timestamp and state == self.state:
                self.baselined = True
            return None
        previous, ready = self.state, self.baselined
        self.state, self.timestamp, self.baselined = state, timestamp, True
        if (not ready or retained or previous is None or previous == state
                or now - timestamp > self.max_age):
            return None
        return state
