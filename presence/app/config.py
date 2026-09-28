"""Configuración del servicio de presencia, leída del entorno una sola vez."""
import os
from dataclasses import dataclass

Zone = tuple[float, float, float, float]

# Valor por defecto de CAMERA_GATEWAY_HOSTPORT en docker-compose.yml: un destino
# que no existe. Tratarlo como "sin pasarela" evita un bucle de reconexiones.
UNSET_GATEWAY = "127.0.0.1:1"


def parse_zone(value: str) -> Zone:
    """`x0,y0,x1,y1` normalizados; por defecto la franja derecha del encuadre."""
    parts = [float(item) for item in value.split(",")]
    if len(parts) != 4:
        raise ValueError("PRESENCE_DOOR_ZONE needs four comma-separated numbers")
    x0, y0, x1, y1 = parts
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("PRESENCE_DOOR_ZONE must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
    return x0, y0, x1, y1


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    enabled: bool
    camera_url: str | None
    door_device: str
    door_zone: Zone
    preroll_seconds: float
    postroll_seconds: float
    max_open_seconds: float
    video_delay_seconds: float
    analysis_fps: float
    match_threshold: float
    retention_days: int
    db_path: str
    models_dir: str
    timezone: str
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str | None
    mqtt_password: str | None

    @classmethod
    def from_env(cls, env=os.environ) -> "Settings":
        hostport = (env.get("CAMERA_GATEWAY_HOSTPORT") or "").strip()
        camera_url = (f"ws://{hostport}/api/ws?src=home_camera"
                      if hostport and hostport != UNSET_GATEWAY else None)
        return cls(
            enabled=_bool(env.get("CAMERA_PRESENCE_ENABLED")),
            camera_url=camera_url,
            door_device=env.get("PRESENCE_DOOR_DEVICE", "entrada"),
            door_zone=parse_zone(env.get("PRESENCE_DOOR_ZONE", "0.8,0,1,1")),
            preroll_seconds=max(0.0, float(env.get("PRESENCE_PREROLL_SECONDS", "10"))),
            postroll_seconds=max(1.0, float(env.get("PRESENCE_POSTROLL_SECONDS", "8"))),
            max_open_seconds=max(10.0, float(env.get("PRESENCE_MAX_OPEN_SECONDS", "90"))),
            video_delay_seconds=max(0.0, float(env.get("PRESENCE_VIDEO_DELAY_SECONDS", "1"))),
            analysis_fps=min(12.0, max(1.0, float(env.get("PRESENCE_ANALYSIS_FPS", "4")))),
            match_threshold=float(env.get("PRESENCE_MATCH_THRESHOLD", "0.363")),
            retention_days=max(1, int(env.get("PRESENCE_RETENTION_DAYS", "30"))),
            db_path=env.get("PRESENCE_DB_PATH", "/data/presence.sqlite3"),
            models_dir=env.get("PRESENCE_MODELS_DIR", "/app/models"),
            timezone=env.get("NOTIFICATION_TIMEZONE", "Europe/Madrid"),
            mqtt_host=env.get("MQTT_HOST", "mosquitto"),
            mqtt_port=int(env.get("MQTT_PORT", "1883")),
            mqtt_user=env.get("MQTT_USER"),
            mqtt_password=env.get("MQTT_PASSWORD"),
        )

    @property
    def door_sensor_id(self) -> str:
        """Mismo identificador que el catálogo del backend (`entrada_door`)."""
        return f"{self.door_device.replace('-', '_')}_door"
