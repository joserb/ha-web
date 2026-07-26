import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SensorDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    topic: str = Field(pattern=r"^[a-zA-Z0-9_/-]+$", max_length=128)
    location: str = Field(pattern=r"^[a-zA-Z0-9_/-]+$", max_length=128)
    location_label: str = Field(min_length=1, max_length=64)
    measurement: str = Field(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64)
    label: str = Field(min_length=1, max_length=64)
    family: str = Field(pattern=r"^[a-z0-9_]+$")
    kind: str = Field(pattern=r"^[a-z0-9_]+$")
    card: str = Field(pattern=r"^(meter|timeline|status)$")
    unit: str | None = Field(default=None, max_length=16)
    minimum: float | None = None
    maximum: float | None = None
    warning_above: float | None = None
    warning_below: float | None = None
    stale_after_seconds: int = Field(gt=0, le=31_536_000)

    @model_validator(mode="after")
    def validate_topic_and_range(self):
        expected_topic = f"{self.location}/{self.measurement}"
        if self.topic != expected_topic:
            raise ValueError(f"topic must be {expected_topic!r}")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum >= self.maximum:
                raise ValueError("minimum must be lower than maximum")
        return self


class SensorCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)

    sensors: tuple[SensorDefinition, ...]

    @model_validator(mode="after")
    def validate_unique_identifiers(self):
        ids = [sensor.id for sensor in self.sensors]
        topics = [sensor.topic for sensor in self.sensors]
        if len(ids) != len(set(ids)):
            raise ValueError("sensor ids must be unique")
        if len(topics) != len(set(topics)):
            raise ValueError("sensor topics must be unique")
        return self


@lru_cache
def load_catalog() -> SensorCatalog:
    path = Path(__file__).with_name("sensors.json")
    return SensorCatalog.model_validate_json(path.read_text(encoding="utf-8"))


METRIC_DEFINITIONS = {
    "temperature": {
        "measurement": "temp", "label": "Temperatura", "family": "temperatures",
        "kind": "temperature", "card": "meter", "unit": "°C",
        "minimum": -10, "maximum": 50,
    },
    "humidity": {
        "measurement": "humidity", "label": "Humedad", "family": "humidities",
        "kind": "humidity", "card": "meter", "unit": "%",
        "minimum": 0, "maximum": 100, "warning_above": 70,
    },
    "pressure": {
        "measurement": "pressure", "label": "Presión", "family": "pressures",
        "kind": "pressure", "card": "meter", "unit": "hPa",
        "minimum": 900, "maximum": 1100,
    },
    "battery": {
        "measurement": "battery", "label": "Batería", "family": "batteries",
        "kind": "battery", "card": "meter", "unit": "%",
        "minimum": 0, "maximum": 100, "warning_below": 20,
    },
}


def build_zro_catalog(devices: dict[str, dict]) -> SensorCatalog:
    sensors = []
    for device, state in sorted(devices.items()):
        location = f"home/{device}"
        location_label = device.replace("-", " ").title()
        for source, definition in METRIC_DEFINITIONS.items():
            value = state.get(source)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            measurement = definition["measurement"]
            sensors.append({
                "id": f"{device.replace('-', '_')}_{measurement}",
                "topic": f"{location}/{measurement}",
                "location": location,
                "location_label": location_label,
                **definition,
                "stale_after_seconds": 86400,
            })
        if state.get("type") == "contact":
            sensors.append({
                "id": f"{device.replace('-', '_')}_door",
                "topic": f"{location}/door",
                "location": location,
                "location_label": location_label,
                "measurement": "door",
                "label": "Puerta",
                "family": "doors",
                "kind": "door",
                "card": "timeline",
                "stale_after_seconds": 86400,
            })
        elif state.get("type") == "vibration":
            sensors.append({
                "id": f"{device.replace('-', '_')}_vibration",
                "topic": f"{location}/vibration",
                "location": location,
                "location_label": location_label,
                "measurement": "vibration",
                "label": "Vibration",
                "family": "vibrations",
                "kind": "vibration",
                "card": "timeline",
                "stale_after_seconds": 86400,
            })
    return SensorCatalog.model_validate({"sensors": sensors})
