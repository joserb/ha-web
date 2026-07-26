import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiomqtt
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from app.catalog import build_zro_catalog, load_catalog
from app.current_state import CurrentState, build_recovered_states
from app.time_ranges import TimeRange, get_legacy_hours_spec, get_time_range_spec
from app.zro_env import decode_env_message, normalize_device

logger = logging.getLogger(__name__)

# Config InfluxDB
INFLUX_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUX_ORG = os.getenv("INFLUXDB_ORG")
INFLUX_BUCKET = os.getenv("INFLUXDB_BUCKET")

influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)
query_api = influx_client.query_api()

# Estado en memoria
connected_clients: list[WebSocket] = []
current_states: dict[str, CurrentState] = {}
zro_devices: dict[str, dict] = {}


def recover_current_states():
    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: 0)
      |> filter(fn: (r) => r._measurement == "sensor")
      |> filter(fn: (r) => exists r.location and exists r.measurement)
      |> group(columns: ["location", "measurement", "_field"])
      |> last()
    '''
    rows = []
    for table in query_api.query(query):
        for record in table.records:
            rows.append({
                "location": record.values.get("location"),
                "measurement": record.values.get("measurement"),
                "field": record.get_field(),
                "value": record.get_value(),
                "time": record.get_time(),
            })
    current_states.update(build_recovered_states(rows))
    logger.info("Recovered %d current sensor states from InfluxDB", len(current_states))


def write_to_influx(topic: str, payload: str, timestamp: datetime | None = None):
    """Intenta parsear el payload como JSON y guardar cada campo numérico."""
    try:
        data = json.loads(payload)
        if isinstance(data, dict):
            point = Point("sensor")
            # topic como tag: "home/salon/temp" → location=home/salon, field=temp
            parts = topic.rsplit("/", 1)
            if len(parts) == 2:
                point = point.tag("location", parts[0]).tag("measurement", parts[1])
            else:
                point = point.tag("topic", topic)

            for key, value in data.items():
                if isinstance(value, (int, float)):
                    point = point.field(key, float(value))
                else:
                    point = point.field(key, str(value))

            write_api.write(bucket=INFLUX_BUCKET, record=point.time(timestamp) if timestamp else point)
        else:
            # Payload es un valor simple
            try:
                value = float(payload)
                parts = topic.rsplit("/", 1)
                point = Point("sensor")
                if len(parts) == 2:
                    point = point.tag("location", parts[0]).tag("measurement", parts[1]).field("value", value)
                else:
                    point = point.tag("topic", topic).field("value", value)
                write_api.write(bucket=INFLUX_BUCKET, record=point.time(timestamp) if timestamp else point)
            except ValueError:
                pass
    except json.JSONDecodeError:
        # Payload no es JSON, intenta como número
        try:
            value = float(payload)
            point = Point("sensor").tag("topic", topic).field("value", value)
            write_api.write(bucket=INFLUX_BUCKET, record=point.time(timestamp) if timestamp else point)
        except ValueError:
            # Guardar como estado string (ej: puerta "open"/"closed")
            parts = topic.rsplit("/", 1)
            point = Point("sensor")
            if len(parts) == 2:
                point = point.tag("location", parts[0]).tag("measurement", parts[1]).field("state", payload.strip())
            else:
                point = point.tag("topic", topic).field("state", payload.strip())
            write_api.write(bucket=INFLUX_BUCKET, record=point.time(timestamp) if timestamp else point)


async def handle_zro_env_message(topic: str, payload: str) -> bool:
    if not topic.startswith("/ZRO/env/"):
        return False
    try:
        devices = decode_env_message(topic, payload)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Invalid zro-pi environment payload on %s", topic)
        return True

    zro_devices.update(devices)
    for device, data in devices.items():
        for reading in normalize_device(device, data):
            state = CurrentState(reading.payload, reading.updated_at, "zro-pi")
            previous = current_states.get(reading.topic)
            current_states[reading.topic] = state
            if previous is None or previous.updated_at != reading.updated_at:
                await asyncio.to_thread(
                    write_to_influx,
                    reading.topic,
                    reading.payload,
                    reading.updated_at,
                )
            message = json.dumps({
                "topic": reading.topic,
                "payload": reading.payload,
                "updated_at": reading.updated_at.isoformat(),
                "source": "zro-pi",
            })
            for ws in connected_clients.copy():
                try:
                    await ws.send_text(message)
                except Exception:
                    connected_clients.remove(ws)
    return True


async def mqtt_listener():
    """Se suscribe a MQTT y reenvía a WebSocket + InfluxDB."""
    while True:
        try:
            async with aiomqtt.Client(
                "mosquitto",
                username=os.getenv("MQTT_USER"),
                password=os.getenv("MQTT_PASSWORD"),
            ) as client:
                await client.subscribe("#")
                async for message in client.messages:
                    topic = str(message.topic)
                    payload = message.payload.decode()
                    if await handle_zro_env_message(topic, payload):
                        continue
                    current_states[topic] = CurrentState(
                        payload=payload,
                        updated_at=datetime.now(timezone.utc),
                        source="mqtt",
                    )

                    # Guardar en InfluxDB
                    await asyncio.to_thread(write_to_influx, topic, payload)

                    # Reenviar a WebSocket
                    data = json.dumps({
                        "topic": topic,
                        "payload": payload,
                        "updated_at": current_states[topic].updated_at.isoformat(),
                        "source": "mqtt",
                    })
                    for ws in connected_clients.copy():
                        try:
                            await ws.send_text(data)
                        except Exception:
                            connected_clients.remove(ws)
        except Exception:
            logger.exception("MQTT listener failed; retrying in 5 seconds")
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await asyncio.to_thread(recover_current_states)
    except Exception:
        logger.exception("Could not recover current states from InfluxDB")
    task = asyncio.create_task(mqtt_listener())
    yield
    task.cancel()
    influx_client.close()


app = FastAPI(lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok", "topics": list(current_states.keys())}


@app.get("/api/catalog")
async def catalog():
    return build_zro_catalog(zro_devices) if zro_devices else load_catalog()


@app.get("/api/sensors")
async def sensors():
    result = []
    now = datetime.now(timezone.utc)
    sensor_catalog = build_zro_catalog(zro_devices) if zro_devices else load_catalog()
    for sensor in sensor_catalog.sensors:
        state = current_states.get(sensor.topic)
        age_seconds = None if state is None else max(
            0,
            int((now - state.updated_at).total_seconds()),
        )
        result.append({
            **sensor.model_dump(),
            "current": None if state is None else {
                "payload": state.payload,
                "updated_at": state.updated_at.isoformat(),
                "source": state.source,
                "age_seconds": age_seconds,
                "stale": age_seconds > sensor.stale_after_seconds,
            },
        })
    return result


@app.get("/api/history")
async def history(
    location: str = Query(pattern=r"^[a-zA-Z0-9_/-]+$", max_length=128),
    measurement: str = Query(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64),
    period: TimeRange | None = Query(default=None, alias="range"),
    hours: int | None = Query(default=None, ge=1, le=8760),
):
    """Devuelve histórico de un sensor. Ej: /api/history?location=home/salon&measurement=temp"""
    spec = (
        get_legacy_hours_spec(hours)
        if hours is not None and period is None
        else get_time_range_spec(period or TimeRange.DAY_1)
    )
    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {spec.start})
      |> filter(fn: (r) => r._measurement == "sensor")
      |> filter(fn: (r) => r.location == "{location}")
      |> filter(fn: (r) => r._field == "{measurement}" or (r._field == "value" and r.measurement == "{measurement}"))
      |> aggregateWindow(every: {spec.window}, fn: mean, createEmpty: false)
      |> yield(name: "mean")
    '''
    tables = query_api.query(query)
    results = []
    for table in tables:
        for record in table.records:
            results.append({
                "time": record.get_time().isoformat(),
                "field": record.get_field(),
                "value": record.get_value()
            })
    return results


@app.get("/api/events")
async def events(
    location: str = Query(pattern=r"^[a-zA-Z0-9_/-]+$", max_length=128),
    measurement: str = Query(pattern=r"^[a-zA-Z0-9_-]+$", max_length=64),
    period: TimeRange | None = Query(default=None, alias="range"),
    hours: int | None = Query(default=None, ge=1, le=8760),
):
    """Devuelve eventos individuales (sin agregar) de un sensor. Ej: /api/events?location=home/entrada&measurement=door"""
    spec = (
        get_legacy_hours_spec(hours)
        if hours is not None and period is None
        else get_time_range_spec(period or TimeRange.DAY_1)
    )
    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {spec.start})
      |> filter(fn: (r) => r._measurement == "sensor")
      |> filter(fn: (r) => r.location == "{location}")
      |> filter(fn: (r) => r.measurement == "{measurement}")
      |> filter(fn: (r) => r._field == "state")
      |> sort(columns: ["_time"])
    '''
    tables = query_api.query(query)
    results = []
    for table in tables:
        for record in table.records:
            results.append({
                "time": record.get_time().isoformat(),
                "value": record.get_value()
            })
    return results


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)

    for topic, state in current_states.items():
        await ws.send_text(json.dumps({
            "topic": topic,
            "payload": state.payload,
            "updated_at": state.updated_at.isoformat(),
            "source": state.source,
        }))

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if "topic" in msg and "payload" in msg:
                async with aiomqtt.Client(
                    "mosquitto",
                    username=os.getenv("MQTT_USER"),
                    password=os.getenv("MQTT_PASSWORD"),
                ) as client:
                    await client.publish(msg["topic"], msg["payload"])
    except WebSocketDisconnect:
        connected_clients.remove(ws)
