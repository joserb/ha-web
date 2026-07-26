import json
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class EnvReading:
    topic: str
    payload: str
    updated_at: datetime


METRIC_ALIASES = {
    "temperature": "temp",
    "humidity": "humidity",
    "pressure": "pressure",
    "battery": "battery",
}


def parse_updated_at(value) -> datetime:
    if not isinstance(value, str):
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_device(device: str, data: dict) -> list[EnvReading]:
    updated_at = parse_updated_at(data.get("updated_at"))
    readings = []
    for source, measurement in METRIC_ALIASES.items():
        value = data.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            readings.append(EnvReading(
                topic=f"home/{device}/{measurement}",
                payload=str(value),
                updated_at=updated_at,
            ))

    device_type = data.get("type")
    state = data.get("state")
    if device_type == "contact" and isinstance(state, str):
        readings.append(EnvReading(
            topic=f"home/{device}/door",
            payload=state.lower(),
            updated_at=updated_at,
        ))
    elif device_type == "vibration" and isinstance(state, str):
        readings.append(EnvReading(
            topic=f"home/{device}/vibration",
            payload=state.lower(),
            updated_at=updated_at,
        ))
    return readings


def decode_env_message(topic: str, payload: str) -> dict[str, dict]:
    data = json.loads(payload)
    if topic == "/ZRO/env/state":
        devices = data.get("devices")
        return devices if isinstance(devices, dict) else {}
    prefix = "/ZRO/env/"
    if topic.startswith(prefix) and isinstance(data, dict):
        return {topic[len(prefix):]: data}
    return {}
