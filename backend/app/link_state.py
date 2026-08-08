"""Estado de los dos tramos que el backend no puede comprobar por sí mismo.

Estar conectado al broker del VPS solo demuestra el tramo local: no dice nada
del bridge hacia `pihomeblk-1` ni de si el servicio `zro-pi` sigue vivo en la
Raspberry. Esos dos hechos llegan como mensajes MQTT normales:

- `/ZRO/bridge/state`: notificación del propio Mosquitto (`notification_topic`
  en `mosquitto/config/conf.d/bridge.conf`), retenida, con payload `1` (arriba)
  o `0` (abajo).
- `/ZRO/pi/availability`: last will retenida del servicio `zro-pi`,
  `online` / `offline`.

El parseo es estricto a propósito: cualquier otro payload significa que estamos
leyendo un topic que ha escrito otro, y es preferible declarar el tramo
desconocido (`None`) antes que inventar un estado sobre el que alguien actuará.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

BRIDGE_STATE_TOPIC = "/ZRO/bridge/state"
PI_AVAILABILITY_TOPIC = "/ZRO/pi/availability"


def parse_bridge_state(payload: str) -> bool | None:
    """`1` → conectado, `0` → desconectado, cualquier otra cosa → desconocido."""
    value = payload.strip()
    if value == "1":
        return True
    if value == "0":
        return False
    return None


def parse_pi_availability(payload: str) -> str | None:
    """Solo se aceptan los dos payloads documentados del last will."""
    value = payload.strip().lower()
    return value if value in {"online", "offline"} else None


@dataclass
class LinkState:
    bridge_connected: bool | None = None
    pi_availability: str | None = None

    def handles(self, topic: str) -> bool:
        return topic in {BRIDGE_STATE_TOPIC, PI_AVAILABILITY_TOPIC}

    def apply(self, topic: str, payload: str) -> bool:
        """Actualiza el tramo correspondiente. Devuelve si el estado ha cambiado.

        Un payload inválido se ignora conservando el valor anterior: es ruido de
        un tercero, no una transición del enlace.
        """
        if topic == BRIDGE_STATE_TOPIC:
            value = parse_bridge_state(payload)
            if value is None:
                logger.warning("Payload de bridge inválido en %s: %r", topic, payload)
                return False
            if self.bridge_connected == value:
                return False
            self.bridge_connected = value
            logger.info("Bridge hacia pihomeblk-1 %s", "arriba" if value else "abajo")
            return True

        if topic == PI_AVAILABILITY_TOPIC:
            value = parse_pi_availability(payload)
            if value is None:
                logger.warning("Payload de availability inválido en %s: %r", topic, payload)
                return False
            if self.pi_availability == value:
                return False
            self.pi_availability = value
            logger.info("Servicio zro-pi %s", value)
            return True

        return False

    def reset(self) -> bool:
        """Olvida ambos tramos cuando se cae NUESTRO enlace con el broker.

        Los dos valores son mensajes retenidos que solo se observan a través de
        ese enlace: mantenerlos sería afirmar un estado que ha podido cambiar
        mientras estábamos ciegos. Se reciben de nuevo al resuscribirse.
        """
        if self.bridge_connected is None and self.pi_availability is None:
            return False
        self.bridge_connected = None
        self.pi_availability = None
        logger.info("Estado del enlace con la Raspberry desconocido (sin broker)")
        return True

    def snapshot(self) -> dict:
        return {
            "bridge_connected": self.bridge_connected,
            "pi_availability": self.pi_availability,
        }
