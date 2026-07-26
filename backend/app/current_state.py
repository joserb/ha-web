import json
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CurrentState:
    payload: str
    updated_at: datetime
    source: str


def build_recovered_states(rows: list[dict]) -> dict[str, CurrentState]:
    grouped: dict[str, dict] = {}
    for row in rows:
        topic = f"{row['location']}/{row['measurement']}"
        entry = grouped.setdefault(topic, {"fields": {}, "updated_at": row["time"]})
        entry["fields"][row["field"]] = row["value"]
        if row["time"] > entry["updated_at"]:
            entry["updated_at"] = row["time"]

    result = {}
    for topic, entry in grouped.items():
        fields = entry["fields"]
        if len(fields) == 1 and "value" in fields:
            payload = str(fields["value"])
        elif len(fields) == 1 and "state" in fields:
            payload = str(fields["state"])
        else:
            payload = json.dumps(fields, separators=(",", ":"))
        result[topic] = CurrentState(
            payload=payload,
            updated_at=entry["updated_at"],
            source="influxdb",
        )
    return result
