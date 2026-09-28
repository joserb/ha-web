"""API privada de presencia bajo `/api/presence`, servida por el nginx del VPS."""
import os
import time
from typing import Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.store import Invalid, NotFound, PresenceStore


class LabelTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person_id: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def one_target(self):
        if (self.person_id is None) == (self.name is None):
            raise ValueError("Give either person_id or name")
        return self


class RenamePerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=80)


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Misma política que las mutaciones de avisos del backend
# (`backend/app/notifications.py`): solo el propio dashboard, por JSON.
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


def build_router(store: PresenceStore, status: Callable[[], dict], threshold: float,
                 changed: Callable[[], None]) -> APIRouter:
    router = APIRouter(prefix="/api/presence")

    def guarded(action):
        try:
            action()
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except Invalid as exc:
            raise HTTPException(422, str(exc)) from None
        changed()
        return state()

    @router.get("/health")
    def health():
        current = status()
        if not current["healthy"]:
            raise HTTPException(503, "Presence worker is not running")
        return {"status": "healthy"}

    @router.get("/state")
    def state(include_archived: bool = False):
        return {**status(), "people": store.people(), "events": store.events(20, include_archived)}

    @router.get("/tracks/{track_id}/image")
    def track_image(track_id: int):
        try:
            jpeg = store.track_image(track_id)
        except NotFound as exc:
            raise HTTPException(404, str(exc)) from None
        # Imagen de una persona: ni cachés intermedias ni del navegador.
        return Response(jpeg, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @router.post("/tracks/{track_id}/label")
    def label_track(track_id: int, body: LabelTrack, request: Request):
        check_mutation(request)

        def action():
            store.require_track(track_id)  # antes de crear a nadie
            person_id = body.person_id or store.add_person(body.name or "", time.time())
            store.label_track(track_id, person_id, threshold)
        return guarded(action)

    @router.post("/tracks/{track_id}/archive")
    def archive_track(track_id: int, body: Empty, request: Request):
        check_mutation(request)
        return guarded(lambda: store.archive_track(track_id, threshold))

    @router.delete("/tracks/{track_id}")
    def delete_track(track_id: int, body: Empty, request: Request):
        check_mutation(request)
        return guarded(lambda: store.delete_track(track_id, threshold))

    @router.post("/events/{event_id}/archive")
    def archive_event(event_id: int, body: Empty, request: Request):
        check_mutation(request)
        return guarded(lambda: store.archive_event(event_id))

    @router.patch("/people/{person_id}")
    def rename_person(person_id: int, body: RenamePerson, request: Request):
        check_mutation(request)
        return guarded(lambda: store.rename_person(person_id, body.name))

    @router.delete("/people/{person_id}")
    def delete_person(person_id: int, body: Empty, request: Request):
        check_mutation(request)
        return guarded(lambda: store.delete_person(person_id, threshold))

    return router
