import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiomqtt
from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from app.catalog import LOCATION_LABELS, build_zro_catalog, load_catalog
from app.current_state import CurrentState, build_recovered_states
from app.intervals import build_intervals, range_start
from app.link_state import LinkState
from app.publish_policy import is_allowed, load_allowlist
from app.time_ranges import TimeRange, get_legacy_hours_spec, get_time_range_spec
from app.zro_env import decode_env_message, normalize_device
from app.notification_rules import NotificationStore
from app.notifications import Notifications
from app.telegram import TelegramSender

logger = logging.getLogger(__name__)

# Config InfluxDB
INFLUX_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUXDB_TOKEN")
INFLUX_ORG = os.getenv("INFLUXDB_ORG")
INFLUX_BUCKET = os.getenv("INFLUXDB_BUCKET")

influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = influx_client.write_api(write_options=SYNCHRONOUS)
query_api = influx_client.query_api()

# Topics en los que el navegador puede publicar. Vacío = ninguno (ver
# app/publish_policy.py).
PUBLISH_ALLOWLIST = load_allowlist(os.getenv("WS_PUBLISH_ALLOWLIST"))

# Estado en memoria
connected_clients: list[WebSocket] = []
current_states: dict[str, CurrentState] = {}
zro_devices: dict[str, dict] = {}
link_state = LinkState()
# Conexión viva con el broker AHORA MISMO, no "el listener arrancó alguna vez":
# esa diferencia es la que /api/health tiene que contar y la que el healthcheck
# de Docker usa para decidir si el contenedor sirve para algo.
mqtt_connected = False
notification_task: asyncio.Task | None = None


async def broadcast(message: dict):
    """Envía un mensaje a todos los clientes WebSocket vivos."""
    data = json.dumps(message)
    for ws in connected_clients.copy():
        try:
            await ws.send_text(data)
        except Exception:
            if ws in connected_clients:
                connected_clients.remove(ws)


def link_message() -> dict:
    """Estado de la cadena backend → broker → bridge → Raspberry."""
    return {
        "type": "link",
        "mqtt_connected": mqtt_connected,
        **link_state.snapshot(),
    }


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


async def handle_zro_env_message(topic: str, payload: str, retained: bool = False) -> bool:
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
            if reading.topic.endswith("/door") and isinstance(data.get("updated_at"), str):
                sensor_id = f"{device.replace('-', '_')}_door"
                notifications.store.observe(
                    sensor_id, LOCATION_LABELS.get(device, device.replace("-", " ").title()),
                    reading.payload, reading.updated_at.timestamp(), retained,
                    datetime.now(timezone.utc).timestamp(),
                )
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
            await broadcast({
                "type": "sensor",
                "topic": reading.topic,
                "payload": reading.payload,
                "updated_at": reading.updated_at.isoformat(),
                "source": "zro-pi",
            })
    return True


async def mqtt_listener():
    """Se suscribe a MQTT y reenvía a WebSocket + InfluxDB."""
    global mqtt_connected
    while True:
        try:
            async with aiomqtt.Client(
                "mosquitto",
                username=os.getenv("MQTT_USER"),
                password=os.getenv("MQTT_PASSWORD"),
            ) as client:
                notifications.store.reset_baselines()
                await client.subscribe("#")
                mqtt_connected = True
                await broadcast(link_message())
                async for message in client.messages:
                    topic = str(message.topic)
                    payload = message.payload.decode()
                    # Bridge y availability no son sensores: no se guardan en
                    # InfluxDB ni entran en el catálogo, solo describen el
                    # camino hasta la Raspberry.
                    if link_state.handles(topic):
                        if link_state.apply(topic, payload):
                            if not link_state.bridge_connected or link_state.pi_availability != "online":
                                notifications.store.reset_baselines()
                            await broadcast(link_message())
                        continue
                    if await handle_zro_env_message(topic, payload, bool(message.retain)):
                        continue
                    current_states[topic] = CurrentState(
                        payload=payload,
                        updated_at=datetime.now(timezone.utc),
                        source="mqtt",
                    )

                    # Guardar en InfluxDB
                    await asyncio.to_thread(write_to_influx, topic, payload)

                    # Reenviar a WebSocket
                    await broadcast({
                        "type": "sensor",
                        "topic": topic,
                        "payload": payload,
                        "updated_at": current_states[topic].updated_at.isoformat(),
                        "source": "mqtt",
                    })
        except Exception:
            logger.exception("MQTT listener failed; retrying in 5 seconds")
        # Se ha perdido el enlace con el broker (fallo o cierre): sin él no
        # sabemos nada de los tramos que hay detrás, así que se declaran
        # desconocidos en lugar de seguir mostrando el último retenido.
        forgotten = link_state.reset()
        changed = mqtt_connected or forgotten
        mqtt_connected = False
        if changed:
            await broadcast(link_message())
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global notification_task
    try:
        await asyncio.to_thread(recover_current_states)
    except Exception:
        logger.exception("Could not recover current states from InfluxDB")
    notifications.store = NotificationStore(os.getenv("NOTIFICATION_DB_PATH", "/data/notifications.sqlite3"))
    task = asyncio.create_task(mqtt_listener())
    notification_task = asyncio.create_task(notifications.run())
    try:
        yield
    finally:
        task.cancel()
        notification_task.cancel()
        await asyncio.gather(task, notification_task, return_exceptions=True)
        notifications.store.close()
        influx_client.close()


app = FastAPI(lifespan=lifespan)
notifications = Notifications(
    None,
    TelegramSender(os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", ""),
                   os.getenv("NOTIFICATION_TIMEZONE", "Europe/Madrid")),
    lambda: build_zro_catalog(zro_devices) if zro_devices else load_catalog(),
    broadcast,
)
app.include_router(notifications.router)


def ping_influx() -> bool:
    try:
        return bool(influx_client.ping())
    except Exception:
        logger.warning("InfluxDB no responde al ping", exc_info=True)
        return False


@app.get("/api/health")
async def health():
    """Salud real del backend, no "el proceso sigue en pie".

    Devuelve 503 si falla el broker, InfluxDB o el worker de notificaciones.
    El bridge y la Raspberry se informan pero NO devuelven 503:
    reiniciar el backend no arregla un enlace roto en la otra punta, y hacerlo
    dejaría el dashboard caído además de sin datos nuevos.
    """
    influx_ok = await asyncio.to_thread(ping_influx)
    notification_worker_ok = notification_task is not None and not notification_task.done()
    healthy = mqtt_connected and influx_ok and notification_worker_ok
    return JSONResponse(
        {
            "status": "healthy" if healthy else "unhealthy",
            "mqtt_connected": mqtt_connected,
            "influxdb_connected": influx_ok,
            "notification_worker_running": notification_worker_ok,
            **link_state.snapshot(),
            "topics": list(current_states.keys()),
        },
        status_code=200 if healthy else 503,
    )


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


@app.get("/api/intervals")
async def intervals(
    sensor_id: str = Query(pattern=r"^[a-z0-9_]+$", max_length=96),
    period: TimeRange = Query(default=TimeRange.DAY_1, alias="range"),
):
    sensor_catalog = build_zro_catalog(zro_devices) if zro_devices else load_catalog()
    sensor = next((item for item in sensor_catalog.sensors if item.id == sensor_id), None)
    if sensor is None or sensor.kind not in {"door", "vibration"}:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Timeline sensor not found")
    event_rows = await events(sensor.location, sensor.measurement, period, None)
    now = datetime.now(timezone.utc)
    active_values = {"open"} if sensor.kind == "door" else {"active"}
    normalized = [{**row, "time": datetime.fromisoformat(row["time"])} for row in event_rows]
    result = build_intervals(normalized, active_values, now)
    start = range_start(period, now)
    if period == TimeRange.FOREVER and normalized:
        start = normalized[0]["time"]
    return {
        "sensor_id": sensor.id,
        "range_start": start.isoformat(),
        "range_end": now.isoformat(),
        "intervals": [{**item, "start": item["start"].isoformat(), "end": item["end"].isoformat()} for item in result],
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)

    # El estado del enlace va primero: el cliente pinta la cadena de conexión
    # antes de tener un solo sensor.
    await ws.send_text(json.dumps(link_message()))
    await ws.send_text(json.dumps({"type": "notification_rule", **notifications.snapshot()}))
    for topic, state in current_states.items():
        await ws.send_text(json.dumps({
            "type": "sensor",
            "topic": topic,
            "payload": state.payload,
            "updated_at": state.updated_at.isoformat(),
            "source": state.source,
        }))

    try:
        while True:
            data = await ws.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("Mensaje WebSocket descartado: no es JSON")
                continue
            if not isinstance(msg, dict) or "topic" not in msg or "payload" not in msg:
                continue
            topic = str(msg["topic"])
            # El navegador no publica en cualquier topic: solo en los de la
            # allowlist, vacía mientras no haya panel de actuadores.
            if not is_allowed(topic, PUBLISH_ALLOWLIST):
                logger.warning(
                    "Publicación rechazada en %r: no está en WS_PUBLISH_ALLOWLIST",
                    topic,
                )
                continue
            async with aiomqtt.Client(
                "mosquitto",
                username=os.getenv("MQTT_USER"),
                password=os.getenv("MQTT_PASSWORD"),
            ) as client:
                await client.publish(topic, str(msg["payload"]))
    except WebSocketDisconnect:
        pass
    finally:
        if ws in connected_clients:
            connected_clients.remove(ws)
