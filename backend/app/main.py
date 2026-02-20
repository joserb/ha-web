import asyncio
import json
import os
from contextlib import asynccontextmanager

import aiomqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

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
last_messages: dict[str, str] = {}


def write_to_influx(topic: str, payload: str):
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

            write_api.write(bucket=INFLUX_BUCKET, record=point)
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
                write_api.write(bucket=INFLUX_BUCKET, record=point)
            except ValueError:
                pass
    except json.JSONDecodeError:
        # Payload no es JSON, intenta como número
        try:
            value = float(payload)
            point = Point("sensor").tag("topic", topic).field("value", value)
            write_api.write(bucket=INFLUX_BUCKET, record=point)
        except ValueError:
            # Guardar como estado string (ej: puerta "open"/"closed")
            parts = topic.rsplit("/", 1)
            point = Point("sensor")
            if len(parts) == 2:
                point = point.tag("location", parts[0]).tag("measurement", parts[1]).field("state", payload.strip())
            else:
                point = point.tag("topic", topic).field("state", payload.strip())
            write_api.write(bucket=INFLUX_BUCKET, record=point)


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
                    last_messages[topic] = payload

                    # Guardar en InfluxDB
                    write_to_influx(topic, payload)

                    # Reenviar a WebSocket
                    data = json.dumps({"topic": topic, "payload": payload})
                    for ws in connected_clients.copy():
                        try:
                            await ws.send_text(data)
                        except Exception:
                            connected_clients.remove(ws)
        except Exception:
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(mqtt_listener())
    yield
    task.cancel()
    influx_client.close()


app = FastAPI(lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok", "topics": list(last_messages.keys())}


@app.get("/api/history")
async def history(location: str, measurement: str, hours: int = 24):
    """Devuelve histórico de un sensor. Ej: /api/history?location=home/salon&measurement=temp"""
    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -{hours}h)
      |> filter(fn: (r) => r._measurement == "sensor")
      |> filter(fn: (r) => r.location == "{location}")
      |> filter(fn: (r) => r._field == "{measurement}" or (r._field == "value" and r.measurement == "{measurement}"))
      |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
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
async def events(location: str, measurement: str, hours: int = 24):
    """Devuelve eventos individuales (sin agregar) de un sensor. Ej: /api/events?location=home/entrada&measurement=door"""
    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -{hours}h)
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

    for topic, payload in last_messages.items():
        await ws.send_text(json.dumps({"topic": topic, "payload": payload}))

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