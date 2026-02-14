import asyncio
import json
from contextlib import asynccontextmanager

import aiomqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

# Clientes WebSocket conectados
connected_clients: list[WebSocket] = []

# Último mensaje por topic (para que un cliente nuevo vea datos al conectar)
last_messages: dict[str, str] = {}


async def mqtt_listener():
    """Se suscribe a MQTT y reenvía mensajes a todos los WebSocket."""
    while True:
        try:
            async with aiomqtt.Client("mosquitto") as client:
                await client.subscribe("#")
                async for message in client.messages:
                    topic = str(message.topic)
                    payload = message.payload.decode()
                    last_messages[topic] = payload

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


app = FastAPI(lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok", "topics": list(last_messages.keys())}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.append(ws)

    # Envía el estado actual al conectar
    for topic, payload in last_messages.items():
        await ws.send_text(json.dumps({"topic": topic, "payload": payload}))

    try:
        while True:
            # Recibe comandos del frontend para publicar en MQTT
            data = await ws.receive_text()
            msg = json.loads(data)
            if "topic" in msg and "payload" in msg:
                async with aiomqtt.Client("mosquitto") as client:
                    await client.publish(msg["topic"], msg["payload"])
    except WebSocketDisconnect:
        connected_clients.remove(ws)