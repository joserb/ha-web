"""Identificación por embeddings SFace (128 dimensiones, comparación por coseno).

La galería son las caras que el usuario ha etiquetado. Una trayectoria vota con
cada una de sus caras: gana la persona con más votos por encima del umbral y,
a igualdad, la de mejor coincidencia.
"""
import math
from dataclasses import dataclass
from typing import Iterable, Sequence

Embedding = Sequence[float]
Gallery = list[tuple[int, Embedding]]  # (person_id, embedding)


@dataclass(frozen=True)
class Match:
    person_id: int | None
    score: float


def cosine(a: Embedding, b: Embedding) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def best_match(embedding: Embedding, gallery: Gallery, threshold: float) -> Match:
    best = Match(None, 0.0)
    for person_id, sample in gallery:
        score = cosine(embedding, sample)
        if score > best.score:
            best = Match(person_id, score)
    return best if best.score >= threshold else Match(None, best.score)


def identify(embeddings: Iterable[Embedding], gallery: Gallery, threshold: float) -> Match:
    votes: dict[int, list[float]] = {}
    best_unknown = 0.0
    for embedding in embeddings:
        match = best_match(embedding, gallery, threshold)
        if match.person_id is None:
            best_unknown = max(best_unknown, match.score)
        else:
            votes.setdefault(match.person_id, []).append(match.score)
    if not votes:
        return Match(None, best_unknown)
    person_id, scores = max(votes.items(), key=lambda item: (len(item[1]), max(item[1])))
    return Match(person_id, max(scores))
