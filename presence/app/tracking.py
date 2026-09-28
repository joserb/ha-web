"""Seguimiento de personas entre frames. Sin OpenCV: solo cajas normalizadas.

Una trayectoria es la secuencia de apariciones de una misma persona. Se asocian
detecciones consecutivas por solape y, si no lo hay (alguien que camina rápido
a 4 fps), por cercanía de centros. Es deliberadamente simple: la escena de una
puerta rara vez tiene más de dos o tres personas a la vez.
"""
from dataclasses import dataclass, field

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 en [0, 1]

MAX_FACES_PER_TRACK = 8


@dataclass(frozen=True)
class FaceSample:
    embedding: tuple[float, ...]
    quality: float  # área relativa × confianza del detector
    jpeg: bytes


@dataclass(frozen=True)
class Detection:
    box: Box
    score: float
    face: FaceSample | None = None


@dataclass(frozen=True)
class Observation:
    t: float
    box: Box


@dataclass
class Track:
    id: int
    observations: list[Observation] = field(default_factory=list)
    faces: list[FaceSample] = field(default_factory=list)

    @property
    def first(self) -> Observation:
        return self.observations[0]

    @property
    def last(self) -> Observation:
        return self.observations[-1]

    def add(self, t: float, detection: Detection):
        self.observations.append(Observation(t, detection.box))
        if detection.face is not None:
            self.faces.append(detection.face)
            self.faces.sort(key=lambda face: face.quality, reverse=True)
            del self.faces[MAX_FACES_PER_TRACK:]


def iou(a: Box, b: Box) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    inter = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def center(box: Box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def center_distance(a: Box, b: Box) -> float:
    (ax, ay), (bx, by) = center(a), center(b)
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


class Tracker:
    def __init__(self, max_gap: float = 2.5, min_iou: float = 0.15, max_jump: float = 0.2):
        self.max_gap = max_gap
        self.min_iou = min_iou
        self.max_jump = max_jump
        self._tracks: list[Track] = []

    def update(self, t: float, detections: list[Detection]):
        active = [track for track in self._tracks if 0 <= t - track.last.t <= self.max_gap]
        candidates = []
        for ti, track in enumerate(active):
            for di, detection in enumerate(detections):
                overlap = iou(track.last.box, detection.box)
                if overlap >= self.min_iou:
                    candidates.append((1 - overlap, ti, di))
                else:
                    distance = center_distance(track.last.box, detection.box)
                    if distance <= self.max_jump:
                        # Siempre detrás de cualquier asociación por solape.
                        candidates.append((1 + distance, ti, di))
        used_tracks, used_detections = set(), set()
        for _, ti, di in sorted(candidates):
            if ti in used_tracks or di in used_detections:
                continue
            used_tracks.add(ti)
            used_detections.add(di)
            active[ti].add(t, detections[di])
        for di, detection in enumerate(detections):
            if di not in used_detections:
                track = Track(len(self._tracks) + 1)
                track.add(t, detection)
                self._tracks.append(track)

    def tracks(self, min_observations: int = 2) -> list[Track]:
        """Trayectorias con evidencia suficiente: un falso positivo aislado de
        un frame no es una persona, pero una cara reconocible sí lo es."""
        return [track for track in self._tracks
                if len(track.observations) >= min_observations or track.faces]
