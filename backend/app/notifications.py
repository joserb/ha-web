"""Notification API, worker and origin policy for the private dashboard."""
import asyncio
import os
import time
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.notification_rules import NotificationStore, RuleConflict
from app.telegram import TelegramSender


class EnableRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    duration: Literal["1h", "4h", "8h", "1d", "7d"]
    version: int = Field(ge=0)
    request_id: UUID


class DisableRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0)


def allowed_origins() -> set[str]:
    configured = os.getenv("NOTIFICATION_ALLOWED_ORIGINS", "")
    if configured.strip():
        return {value.strip().rstrip("/") for value in configured.split(",") if value.strip()}
    hosts = {"127.0.0.1", "localhost", "charo-vps"}
    if os.getenv("TS_BIND_IP"):
        hosts.add(os.environ["TS_BIND_IP"])
    return {f"http://{host}:8080" for host in hosts}


def check_mutation(request: Request):
    origin = request.headers.get("origin", "")
    if origin not in allowed_origins() or urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Dashboard origin is not allowed")
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(415, "JSON is required")
    if request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}:
        raise HTTPException(403, "Cross-site changes are not allowed")


class Notifications:
    def __init__(self, store: NotificationStore, sender: TelegramSender, catalog, broadcast):
        self.store = store
        self.sender = sender
        self.catalog = catalog
        self.broadcast = broadcast
        self.last_snapshot = None
        self.router = APIRouter(prefix="/api/notification-rules")
        self.router.add_api_route("", self.get_rules, methods=["GET"])
        self.router.add_api_route("/{sensor_id}", self.enable, methods=["PUT"])
        self.router.add_api_route("/{sensor_id}", self.disable, methods=["DELETE"])

    def snapshot(self):
        now = time.time()
        ids = {sensor.id for sensor in self.catalog().sensors if sensor.kind == "door"}
        ids.update(rule["sensor_id"] for rule in self.store.rules(now))
        return {"configured": self.sender.configured,
                "rules": [self.store.rule(sensor_id, now) for sensor_id in sorted(ids)]}

    async def get_rules(self):
        return self.snapshot()

    async def changed(self):
        state = self.snapshot()
        if state != self.last_snapshot:
            self.last_snapshot = state
            await self.broadcast({"type": "notification_rule", **state})

    async def enable(self, sensor_id: str, body: EnableRule, request: Request):
        check_mutation(request)
        if not any(sensor.id == sensor_id and sensor.kind == "door" for sensor in self.catalog().sensors):
            raise HTTPException(404, "Door sensor not found")
        if not self.sender.configured:
            raise HTTPException(503, "Telegram is not configured on the server")
        try:
            self.store.enable(sensor_id, body.duration, body.version, str(body.request_id), time.time())
        except RuleConflict as exc:
            raise HTTPException(409, str(exc)) from None
        await self.changed()
        return self.snapshot()

    async def disable(self, sensor_id: str, body: DisableRule, request: Request):
        check_mutation(request)
        try:
            self.store.disable(sensor_id, body.version, time.time())
        except RuleConflict as exc:
            raise HTTPException(409, str(exc)) from None
        await self.changed()
        return self.snapshot()

    async def run(self):
        while True:
            await self.changed()
            delivery = self.store.claim(time.time())
            if delivery:
                result = await self.sender.send(delivery)
                self.store.finish(delivery, result.status, result.detail, time.time(), result.retry_after)
                await self.changed()
            await asyncio.sleep(1)
