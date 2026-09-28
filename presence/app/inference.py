"""¿Entró o salió? Dirección de cada persona respecto a la puerta.

La cámara no ve la puerta: queda justo fuera del borde derecho del encuadre
(`PRESENCE_DOOR_ZONE`). Quien entra aparece por esa zona después de abrir y se
adentra en la casa; quien sale cruza la escena hacia ella antes de abrir y ya
no está cuando se cierra. La prueba del usuario —si tras cerrar se sigue
viendo a alguien, entró; si no, salió— es la última red cuando el recorrido no
basta.
"""
from dataclasses import dataclass

from app.identity import Gallery, identify
from app.tracking import Box, FaceSample, Observation, Track, center

ENTERED, LEFT, STAYED, UNCLEAR = "entered", "left", "stayed", "unclear"
HIGH, MEDIUM, LOW = "high", "medium", "low"


@dataclass(frozen=True)
class Window:
    opened_at: float
    closed_at: float | None  # None: la puerta siguió abierta más del tope
    zone: tuple[float, float, float, float]
    grace: float = 1.0


@dataclass(frozen=True)
class Verdict:
    direction: str
    confidence: str


@dataclass(frozen=True)
class PersonResult:
    person_id: int | None
    score: float
    first: Observation
    last: Observation
    verdict: Verdict
    face: FaceSample | None
    snapshot: bytes | None = None


def in_zone(box: Box, zone) -> bool:
    x, y = center(box)
    return zone[0] <= x <= zone[2] and zone[1] <= y <= zone[3]


def classify(first: Observation, last: Observation, window: Window) -> Verdict:
    starts_at_door = in_zone(first.box, window.zone)
    ends_at_door = in_zone(last.box, window.zone)
    before = first.t < window.opened_at - window.grace
    after = window.closed_at is not None and last.t > window.closed_at + window.grace

    if before and after:
        return Verdict(STAYED, HIGH)
    if starts_at_door and not before:
        if after and not ends_at_door:
            return Verdict(ENTERED, HIGH)
        if after or not ends_at_door:
            return Verdict(ENTERED, MEDIUM)
    if ends_at_door and not after:
        if before and not starts_at_door:
            return Verdict(LEFT, HIGH)
        if before or not starts_at_door:
            return Verdict(LEFT, MEDIUM)
    if after:
        return Verdict(ENTERED, LOW)
    if window.closed_at is not None:
        return Verdict(LEFT, LOW)
    return Verdict(UNCLEAR, LOW)


def summarize(tracks: list[Track], window: Window, gallery: Gallery, threshold: float) -> list[PersonResult]:
    """Una fila por persona reconocida y una por trayectoria desconocida.

    Las trayectorias de una misma persona se funden antes de clasificar: una
    oclusión parte el recorrido en dos, pero la dirección es la del conjunto.
    """
    groups: dict[object, list[tuple[Track, float]]] = {}
    for track in tracks:
        match = identify((face.embedding for face in track.faces), gallery, threshold)
        key = match.person_id if match.person_id is not None else ("unknown", track.id)
        groups.setdefault(key, []).append((track, match.score))

    results = []
    for key, members in groups.items():
        observations = sorted((obs for track, _ in members for obs in track.observations), key=lambda obs: obs.t)
        faces = [face for track, _ in members for face in track.faces]
        snapshots = [track.snapshot for track, _ in members if track.snapshot is not None]
        first, last = observations[0], observations[-1]
        results.append(PersonResult(
            person_id=key if isinstance(key, int) else None,
            score=max(score for _, score in members),
            first=first,
            last=last,
            verdict=classify(first, last, window),
            face=max(faces, key=lambda face: face.quality) if faces else None,
            snapshot=max(snapshots, key=lambda snap: snap.quality).jpeg if snapshots else None,
        ))
    results.sort(key=lambda result: result.first.t)
    return results


def describe(results: list[tuple[str, str, str]], status: str) -> str:
    """Texto para Telegram. `results` son (nombre, dirección, confianza)."""
    if status == "no_video":
        return "🚪 Puerta abierta · sin vídeo de la cámara"
    lines = []
    for name, direction, confidence in results:
        if direction == STAYED:
            continue
        text = {ENTERED: f"{name} ha entrado", LEFT: f"{name} ha salido"}.get(
            direction, f"{name}: movimiento sin dirección clara")
        lines.append(text + (" (poco seguro)" if confidence == LOW else ""))
    if lines:
        return "🏠 " + "; ".join(lines)
    if results:
        return "🚪 Puerta abierta · quien estaba sigue dentro"
    return "🚪 Puerta abierta · no se vio a nadie"
