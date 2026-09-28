"""Servicio de presencia: puerta por MQTT, vídeo por go2rtc, resultado por MQTT.

Publica en `haweb/presence/event` (un evento analizado, con el texto del aviso)
y `haweb/presence/changed` (etiquetas o personas editadas). Ninguno se retiene:
el estado vive en SQLite y el dashboard lo pide por la API al recibir el aviso.
"""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

import aiomqtt
from fastapi import FastAPI

from app.analyzer import Analyzer
from app.api import build_router
from app.config import Settings
from app.door import DoorWatcher, door_reading
from app.store import PresenceStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("presence")

EVENT_TOPIC = "haweb/presence/event"
CHANGED_TOPIC = "haweb/presence/changed"
PURGE_INTERVAL = 6 * 3600

settings = Settings.from_env()
store = PresenceStore(settings.db_path)
stream = None
if settings.enabled and settings.camera_url:
    from app.stream import CameraStream
    stream = CameraStream(settings.camera_url, settings.preroll_seconds)

outbox: asyncio.Queue[tuple[str, dict]] | None = None
loop: asyncio.AbstractEventLoop | None = None
mqtt_connected = False


def publish(topic: str, payload: dict):
    """Seguro desde cualquier hilo; si el broker no está, el mensaje se pierde
    pero el evento sigue guardado y el dashboard lo verá al recargar."""
    if loop is not None and outbox is not None:
        loop.call_soon_threadsafe(outbox.put_nowait, (topic, payload))


analyzer = Analyzer(settings, stream, store, lambda event: publish(EVENT_TOPIC, event))


def status() -> dict:
    worker_ok = analyzer.is_alive() and (stream is None or stream.is_alive())
    return {
        "healthy": worker_ok or not settings.enabled,
        "enabled": settings.enabled,
        "camera_configured": settings.camera_url is not None,
        "mqtt_connected": mqtt_connected,
        "analysing": analyzer.busy,
        "last_error": analyzer.last_error,
        "stream": stream.status() if stream is not None else None,
        "retention_days": settings.retention_days,
    }


async def mqtt_loop():
    global mqtt_connected
    watcher = DoorWatcher()
    while True:
        try:
            async with aiomqtt.Client(settings.mqtt_host, settings.mqtt_port,
                                      username=settings.mqtt_user, password=settings.mqtt_password) as client:
                watcher.reset()
                await client.subscribe("/ZRO/env/#")
                mqtt_connected = True
                sender = asyncio.create_task(send_outbox(client))
                try:
                    async for message in client.messages:
                        reading = door_reading(str(message.topic), message.payload.decode(errors="replace"),
                                               settings.door_device)
                        if reading is None:
                            continue
                        transition = watcher.observe(*reading, bool(message.retain), time.time())
                        if transition and settings.enabled:
                            logger.info("Door %s at %.3f", transition, reading[1])
                            analyzer.door(transition, reading[1])
                finally:
                    sender.cancel()
        except Exception:
            logger.exception("MQTT loop failed; retrying in 5 seconds")
        mqtt_connected = False
        await asyncio.sleep(5)


async def send_outbox(client: aiomqtt.Client):
    while True:
        topic, payload = await outbox.get()
        try:
            await client.publish(topic, json.dumps(payload), qos=1)
        except Exception:
            logger.warning("Could not publish %s", topic)


async def purge_loop():
    while True:
        deleted = await asyncio.to_thread(store.purge, time.time(), settings.retention_days)
        if deleted:
            logger.info("Purged %d presence events older than %d days", deleted, settings.retention_days)
            publish(CHANGED_TOPIC, {})
        await asyncio.sleep(PURGE_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global outbox, loop
    loop = asyncio.get_running_loop()
    outbox = asyncio.Queue()
    if stream is not None:
        stream.start()
    analyzer.start()
    tasks = [asyncio.create_task(mqtt_loop()), asyncio.create_task(purge_loop())]
    logger.info("Presence service started (enabled=%s, camera=%s, preroll=%ss)",
                settings.enabled, settings.camera_url is not None, settings.preroll_seconds)
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if stream is not None:
            stream.stop()
        store.close()


app = FastAPI(lifespan=lifespan)
app.include_router(build_router(store, status, settings.match_threshold, lambda: publish(CHANGED_TOPIC, {})))
