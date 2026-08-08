"""Qué puede publicar el navegador por el WebSocket.

Hasta ahora cualquier cliente conectado podía publicar en cualquier topic del
broker: el WebSocket es público dentro de Tailscale y el broker habla con la
Raspberry a través del bridge, así que era una vía directa desde el navegador a
los actuadores de casa. La lista es una allowlist explícita y **vacía por
defecto**: sin configuración, todo publish se rechaza.

Solo se admiten topics literales. No hay comodines a propósito: un `#` en la
allowlist vuelve a abrir exactamente lo que este cambio cierra, y el panel de
actuadores publicará en un conjunto pequeño y conocido de topics.
"""

import logging

logger = logging.getLogger(__name__)

MAX_TOPIC_LENGTH = 128


def load_allowlist(raw: str | None) -> frozenset[str]:
    """Lee la allowlist de una variable de entorno (topics separados por comas)."""
    if not raw:
        return frozenset()
    topics = set()
    for item in raw.replace("\n", ",").split(","):
        topic = item.strip()
        if not topic:
            continue
        if not _is_publishable(topic):
            logger.warning("Topic ignorado en la allowlist de publicación: %r", topic)
            continue
        topics.add(topic)
    return frozenset(topics)


def is_allowed(topic: str, allowlist: frozenset[str]) -> bool:
    return _is_publishable(topic) and topic in allowlist


def _is_publishable(topic: str) -> bool:
    """Descarta comodines, topics vacíos, `$SYS` y longitudes absurdas."""
    if not topic or len(topic) > MAX_TOPIC_LENGTH:
        return False
    if any(character in topic for character in ("+", "#", "\x00")):
        return False
    return not topic.startswith("$")
