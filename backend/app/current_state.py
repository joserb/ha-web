import json
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CurrentState:
    payload: str
    updated_at: datetime
    source: str


def supersedes(previous: "CurrentState | None", updated_at: datetime) -> bool:
    """¿Esta lectura debe reemplazar al estado actual?

    Solo si es estrictamente más reciente. Al reconectar, el broker reproduce
    los retenidos: traen la última lectura que él guardó, no la última que
    ocurrió. Aceptarlos hacía retroceder el estado actual y pintaba como
    obsoleto un sensor que acababa de reportar, además de deshacer la
    recuperación desde InfluxDB que se hace al arrancar.

    Misma marca de tiempo tampoco reemplaza: el mismo instante llega dos veces
    —por topic individual y por el inventario agregado— y no aporta nada nuevo.
    """
    return previous is None or updated_at > previous.updated_at


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
