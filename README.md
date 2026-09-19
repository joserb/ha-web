# ha-web

Dashboard doméstico propio, con datos actuales de `zro-pi` y compatibilidad con el histórico de Home Assistant.

## Acceso

1. Conecta tu ordenador o móvil a la red Tailscale del VPS.
2. Abre [el dashboard](http://100.120.178.39:8080).

Esta IP procede de `.env.example`; si ha cambiado, usa el valor `TS_BIND_IP` del `.env` en el VPS. También puedes usar [charo-vps](http://charo-vps:8080) si MagicDNS resuelve ese nombre. Usa HTTP y el puerto **8080**.

El servicio se publica en localhost y Tailscale. El acceso público con dominio, TLS y autenticación está pendiente.

Si no carga, comprueba que Tailscale está conectado y que el VPS aparece accesible. Desde el VPS, en `/opt/projects/ha-web`, puedes comprobar:

```bash
docker compose ps
curl -i http://127.0.0.1:8080/api/health
```

La salud devuelve 503 cuando falla MQTT, InfluxDB o el worker de notificaciones; el estado del bridge y de la Pi se informa por separado. Que la web cargue no garantiza que los sensores estén enviando datos recientes.

## Arquitectura actual

```text
Raspberry pihomeblk-1: zro-pi → broker MQTT
                                  ↓ bridge por Tailscale
VPS charo-vps: Mosquitto → FastAPI → InfluxDB
                            ↕ REST / WebSocket
                         Nginx → dashboard React
```

- La telemetría actual llega por `/ZRO/env/#`; el backend la normaliza a las series `home/{dispositivo}/{medida}`.
- Home Assistant fue el origen inicial; su histórico sigue siendo compatible.
- Compose ejecuta Mosquitto, InfluxDB 2, FastAPI y Nginx, que sirve el build de `frontend-react/`.
- La interfaz incluye temperatura, tendencias por familia, timelines de puerta/vibración, rango global, temas y estado de conexión.
- `frontend/` conserva el prototipo anterior y no es la interfaz servida por Compose.

## Estado y documentación

Revisión y despliegue verificados en el VPS: 2026-09-18. Los últimos commits locales (2026-08-08) refuerzan healthchecks y recuperación del stack; la entrega de avisos temporales del 2026-09-18 está desplegada desde el árbol de trabajo.

Quedan pendientes consultas multicanal por lotes, detalles de intervalos al inicio del rango, persistencia de canales, pruebas completas de UI y acceso público autenticado.

- [Contexto técnico y API](claude.md)
- [Operación del host y vigilante](docs/operacion-host.md)
- [Plan general](docs/workplans/01-dashboard-domotico.md)
- [Plan de interfaz React](docs/workplans/02-react-dashboard-ui.md)
- [Plan de avisos temporales por Telegram](docs/workplans/03-telegram-door-alerts.md)
- [Viabilidad del visor de cámara](docs/workplans/04-camera-viewer-feasibility.md)
- [Plan del widget de cámara](docs/workplans/05-camera-dashboard-widget.md)

Los planes incluyen objetivos futuros; sus requisitos no implican que toda la funcionalidad esté terminada.

## Cambio de topics MQTT (2026-09-18)

La Pi publica ahora `zro/env/#` y `zro/pi/availability`. El bridge traduce el prefijo remoto `zro/` al local `/ZRO/`, conservando el contrato del backend y el histórico. La plantilla `mosquitto/config/conf.d/bridge.conf.example` incluye ambas reglas de entrada con QoS 1. Escuchar `/ZRO/...` directamente en la Pi deja datos antiguos y un estado offline retenido.

Sintaxis del remapeo: [documentación de Mosquitto](https://mosquitto.org/man/mosquitto-conf-5.html).

## Avisos temporales por Telegram

En la tarjeta **Entrance Door**, selecciona `1h`, `4h`, `8h`, `1d` o `7d` y activa **Telegram alerts**. La hora de fin se confirma desde el servidor. **Extend** amplía hasta al menos la duración elegida desde ahora; apagar el interruptor cancela los avisos pendientes. Funciona con el navegador cerrado y conserva la caducidad tras reinicios.

Solo se avisa de nuevas transiciones de puerta cerrada a abierta. Activar cuando ya está abierta no envía un aviso inmediato. Los eventos retenidos, antiguos o repetidos no disparan avisos. Tras una desconexión puede perderse una apertura: no se reconstruyen avisos históricos. Un envío ya iniciado puede completarse aunque se apague el interruptor.

Configuración: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `NOTIFICATION_TIMEZONE` (por defecto `Europe/Madrid`). El destino es común para quienes accedan al dashboard. La API informa si falta configuración; las credenciales nunca se envían al navegador. Si Telegram no confirma un envío, se muestra como entrega desconocida sin reintento automático para evitar duplicados.

Las reglas y cola viven en el volumen `notification-data`, en `/data/notifications.sqlite3`; incluirlo en las copias de seguridad y no eliminarlo al recrear contenedores. Al usar otro nombre DNS, añadir su origen exacto a `NOTIFICATION_ALLOWED_ORIGINS`; el acceso sigue limitado a Tailscale/localhost.

Pruebas del backend (en un entorno virtual):

```bash
pip install -r backend/requirements-dev.txt
PYTHONPATH=backend python -m unittest discover -s backend/tests
npm --prefix frontend-react run build
```


## Cámara doméstica: conexión verificada, widget planificado

La EZVIZ C6N está en `192.168.1.199`. Se ha verificado desde la Raspberry el acceso RTSP autenticado por TCP: vídeo H.264 a 1920 × 1080 y audio AAC mono a 16 kHz. Las credenciales no están guardadas en el repositorio.

El [plan del widget](docs/workplans/05-camera-dashboard-widget.md) propone una tarjeta **Home camera** con **View live**, parada, pantalla completa y audio silenciado inicialmente. El vídeo se abrirá bajo demanda mediante go2rtc en la Pi y el proxy del VPS por Tailscale. **La pasarela y el widget todavía no están implementados.**
