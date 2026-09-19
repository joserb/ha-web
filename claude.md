# CLAUDE.md — Contexto del proyecto ha-web

Actualizado el 2026-09-18. Despliegue verificado en el VPS con backend, Nginx y worker de notificaciones saludables; reglas Telegram apagadas tras la entrega.

Guía de entrada y acceso: [README.md](README.md).

## Entorno de ejecución

- **VPS**: Hetzner Cloud, Ubuntu Server
- **Acceso**: SSH (claves), Tailscale
- **Firewall**: Configurado, sin puertos públicos innecesarios
- **Desarrollo**: VS Code Remote-SSH desde Windows (claves copiadas desde WSL)
- **Repo**: git@github.com:joserb/ha-web.git
- **Ruta del proyecto**: `/opt/projects/ha-web`

## Filosofía del servidor

- Server-first, headless (sin escritorio)
- Estabilidad, reproducibilidad, mínima superficie de ataque
- Cambios deliberados e incrementales
- Configuración explícita sobre comportamiento implícito
- Sin contenedores privilegiados, sin Docker socket montado

## Coexistencia con OpenClaw / Moltbot

- OpenClaw está desplegado en el mismo VPS via Docker Compose
- Este proyecto (ha-web) vive en `/opt/projects/ha-web` con su propio Docker Compose
- No comparten red ni volúmenes. Son stacks independientes
- Futura integración con Moltbot vía API (no acoplamiento directo)

## Stack ha-web (4 servicios Docker Compose)

- **Mosquitto**: Broker MQTT con autenticación (usuario: haweb, password_file)
- **InfluxDB 2**: Base de datos de series temporales para histórico de sensores (bucket: sensors, org: haweb)
- **FastAPI**: Backend Python asíncrono — se suscribe a MQTT, escribe en InfluxDB, reenvía datos por WebSocket, expone API REST
- **Nginx**: Sirve frontend estático + reverse proxy a FastAPI (/api/ y /ws)

## Puertos

- Mosquitto: 127.0.0.1:1883 + IP_TAILSCALE:1883
- FastAPI: 127.0.0.1:8000
- Nginx: 127.0.0.1:8080 + IP_TAILSCALE:8080
- InfluxDB: 127.0.0.1:8086
- Nada expuesto a internet, solo localhost y Tailscale

## Red Tailscale

- VPS y Raspberry (`pihomeblk-1`, servicio `zro-pi`) están en la misma red Tailscale
- PC Windows de desarrollo también en Tailscale
- MQTT accesible vía Tailscale para el bridge y herramientas como MQTT Studio

## Fuente actual: zro-pi (Raspberry)

- El servicio Python `zro-pi` en `pihomeblk-1` es la fuente del inventario doméstico actual.
- El broker primario está en la Raspberry; el Mosquitto del VPS recibe `/ZRO/env/#` mediante un bridge sobre Tailscale.
- `/ZRO/env/state` contiene el inventario agregado; `/ZRO/env/{dispositivo}` contiene lecturas individuales.
- El backend normaliza las lecturas a `home/{dispositivo}/{medida}` y conserva el timestamp de origen.
- El catálogo se genera desde los dispositivos recibidos; `backend/app/sensors.json` sirve de fallback cuando no hay inventario de zro-pi.
- `/ZRO/bridge/state` informa del bridge y `/ZRO/pi/availability` de la disponibilidad de zro-pi.
- Home Assistant fue la fuente original. Su histórico sigue siendo compatible, pero ya no define el inventario actual.

## Acceso al dashboard

- Conectar el dispositivo a la misma red Tailscale que el VPS.
- Abrir `http://100.120.178.39:8080` (IP recogida en `.env.example`; la configuración efectiva es `TS_BIND_IP` en el `.env` del VPS).
- Alternativa: `http://charo-vps:8080` si MagicDNS resuelve ese nombre.
- Desde el VPS: `http://127.0.0.1:8080`.
- El acceso público con dominio, TLS y autenticación sigue pendiente.

## Endpoints API

- `GET /api/health`: salud de MQTT e InfluxDB y estado informativo del bridge/Pi. Devuelve 503 si falla MQTT, InfluxDB o el worker de notificaciones.
- `GET /api/catalog`: catálogo de sensores.
- `GET /api/sensors`: catálogo con valores actuales, origen, timestamps y antigüedad.
- `GET /api/history?location=home/salon&measurement=temp&range=1d`: histórico numérico agregado según rango.
- `GET /api/events?location=home/entrada&measurement=door&range=1d`: eventos de estado sin agregar.
- `GET /api/intervals?sensor_id=entrada_door&range=1d`: intervalos de puerta o vibración. La reconstrucción del estado anterior al inicio del rango sigue pendiente.
- Rangos: `1h`, `6h`, `12h`, `1d`, `7d`, `30d`, `3m`, `6m`, `1y`, `forever`. History/events conservan `hours` por compatibilidad.
- `WS /ws`: lecturas `sensor` y estado de conexión `link`, con replay del estado conocido al conectar. Publicación limitada a `WS_PUBLISH_ALLOWLIST`, vacía por defecto.
- Las tendencias aún consultan un sensor por petición; no hay endpoint multicanal por lotes.

## Frontend actual

- `frontend-react/`: React 19, TypeScript, Vite, Tailwind CSS v4, componentes shadcn/ui y Recharts.
- Docker Compose construye una imagen de Nginx con los assets compilados; sirve `/api/` y `/ws` mediante proxy al backend.
- Indicadores SVG semicirculares de temperatura (10–36 °C).
- Tendencias separadas de temperatura, humedad, presión y batería; canales ocultables, sin persistencia todavía.
- Timelines de puerta y vibración con zoom, actualización por WebSocket e intervalos de anchura visual mínima de 6 px.
- Selector global de rango y temas `System`/`Light`/`Dark`, con persistencia local.
- Estado visible de la cadena navegador → backend → broker → bridge → Pi.
- Tarjeta `Home camera` bajo demanda, independiente del estado de la API de sensores.
- `frontend/` y `nginx/default.conf` conservan el prototipo estático anterior; Compose ya no lo sirve.

## Configuración sensible

- Todo en `.env` (nunca en Git). Plantilla comentada en `.env.example`
- Variables: TS_BIND_IP, MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASSWORD, WS_PUBLISH_ALLOWLIST, INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET, INFLUXDB_USER, INFLUXDB_PASSWORD, SENSOR_STALE_AFTER_SECONDS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
- `mosquitto/config/conf.d/bridge.conf` también es local al VPS (plantilla en `bridge.conf.example`)

## Resiliencia

- Los cuatro servicios tienen healthcheck y rotación de logs; `depends_on` espera a `service_healthy`
- `scripts/stack-watchdog.sh` corre en el host por cron cada minuto: recrea contenedores caídos, sin red o `unhealthy`, y el backend si `/api/health` falla ~5 min. Registro en `.health/watchdog.json`, alertas opcionales por Telegram
- Pasos de host (sysctl `ip_nonlocal_bind` y cron): `docs/operacion-host.md`

## Esquema InfluxDB

- Measurement: `sensor`
- Tags: `location` (ej: `home/salon`), `measurement` (ej: `temp`)
- Fields: `value` (float, sensores numéricos), `state` (string, sensores de estado)
- Query de `/api/history` tiene retrocompatibilidad: acepta tanto field `value` con tag `measurement`, como field con nombre igual al measurement (esquema antiguo)

## Próximos pasos

- Completar intervalos en los límites del rango, resúmenes y pruebas de contrato/UI.
- Añadir consultas multicanal por lotes, selector de familias y persistencia de canales.
- Completar configuración del medidor y tendencia compacta por tarjeta.
- Definir retención/downsampling, backups y restauración; verificar configuración del vigilante en el host.
- Implementar acceso público autenticado antes de exponer el dashboard a Internet.
- Actuadores e integración con Moltbot permanecen como ampliaciones futuras.

Los planes en `docs/workplans/` describen también requisitos aún no implementados.

## Cambio de topics MQTT (2026-09-18)

La Pi publica ahora `zro/env/#` y `zro/pi/availability`. El bridge traduce el prefijo remoto `zro/` al local `/ZRO/`, conservando el contrato del backend y el histórico. La plantilla `mosquitto/config/conf.d/bridge.conf.example` incluye ambas reglas de entrada con QoS 1. Escuchar `/ZRO/...` directamente en la Pi deja datos antiguos y un estado offline retenido.

Sintaxis del remapeo: [documentación de Mosquitto](https://mosquitto.org/man/mosquitto-conf-5.html).

## Avisos de puerta implementados (2026-09-18)

- API `GET /api/notification-rules`, `PUT` y `DELETE /api/notification-rules/{sensor_id}`; mutaciones JSON con Origin/Host validados, versión de regla e idempotencia en la activación.
- WebSocket `notification_rule` sincroniza la configuración entre navegadores.
- Interruptor en tarjetas de puerta y duraciones `1h`, `4h`, `8h`, `1d`, `7d`; caducidad en servidor, apagado inicial.
- SQLite en volumen `notification-data` guarda reglas, cursor de eventos y cola de entrega.
- Telegram usa las variables existentes de bot/chat. `NOTIFICATION_TIMEZONE` y `NOTIFICATION_ALLOWED_ORIGINS` son opcionales.
- La detección solo consume puerta normalizada de zro-pi, excluye replay/duplicados y exige frescura de 2 minutos. No depende de tener el dashboard abierto.
- La prueba de apertura física y entrega Telegram real queda a cargo de una activación explícita del usuario; los tests automáticos simulan Telegram.


## Cámara EZVIZ C6N: pasarela y widget implementados (2026-09-19)

- IP confirmada: `192.168.1.199`, RTSP/TCP en 554, ruta `/`, autenticación verificada desde `pihomeblk-1`. Vídeo H.264 1920 × 1080; audio AAC 16 kHz mono.
- Las IP y fallos anteriores de cámara son diagnóstico histórico; no usarlos como configuración actual.
- Credenciales: solo en `camera-gateway/go2rtc.yaml` del host, fuera de Git y nunca en el frontend.
- `camera-gateway/` contiene el Compose de go2rtc **1.9.14** para desplegar en la Raspberry como proyecto independiente, más plantillas sin secretos.
- go2rtc queda reducido a lo imprescindible: `modules: [api, ws, rtsp, mp4]`, `allow_paths: [/api/ws]`, servidor RTSP y WebRTC desactivados, puerto publicado solo en la IP Tailscale de la Pi.
- El navegador conecta a `/camera/home/ws` en su mismo origen. Nginx fija `src=home_camera` con `set $args` y descarta la query del cliente: el manejador `mse` construye el stream desde los parámetros de la petición, así que un `src` libre permitiría reproducir orígenes arbitrarios.
- El transporte es fMP4 sobre WebSocket reproducido con MSE. No pasa por FastAPI, MQTT ni InfluxDB, y no se graba nada.
- `frontend-react/nginx.conf.template` se procesa con envsubst al arrancar el contenedor; `NGINX_ENVSUBST_FILTER=^CAMERA_` protege las variables propias de nginx.
- Interruptor de despliegue: `CAMERA_ENABLED` (por defecto `false`) y `CAMERA_GATEWAY_HOSTPORT` en el `.env` del VPS. Apagado, la tarjeta no se monta y la ruta no tiene destino.
- La tarjeta se renderiza fuera de la condición que oculta el dashboard cuando falla la API de sensores.
- `LIVE` solo mientras la reproducción avanza; congelación de ~10 s, tres reintentos (1, 3 y 5 s) y después Retry manual. Pestaña oculta o tarjeta fuera de vista más de 3 s detienen el vídeo y ofrecen Resume.
- Pasarela desplegada el 2026-09-19 en `pihomeblk-1`, en `~/camera-gateway` (junto a `zro-pi`; en la Pi no existe `/opt/projects`). Verificado desde la Pi y desde el VPS: solo `/api/ws` responde (400), el resto 404, y dentro del contenedor únicamente escucha el 1984.
- `go2rtc.yaml` debe pertenecer a **root** con modo 600. El contenedor corre como root sin `CAP_DAC_OVERRIDE` por `cap_drop: ALL`: con otro propietario no lee la configuración, no avisa y arranca con los valores por defecto, que sirven la interfaz web y `/api/streams` con la URL de origen. El healthcheck exige ahora que `/api/streams` devuelva 404 para detectar justo ese caso.
- **Pendiente**: la cámara está en la red (MAC EZVIZ en `.199`) pero con todos los puertos cerrados —modo privacidad o RTSP desactivado tras reinicio—, y la configuración desplegada conserva el marcador de credenciales. Faltan credenciales, reproducción real, medidas de latencia/bitrate/consumo y el despliegue del lado del VPS. Hasta entonces `CAMERA_ENABLED` sigue en `false`.
- Plan y criterios de aceptación: [05-camera-dashboard-widget.md](docs/workplans/05-camera-dashboard-widget.md); evidencia: [04-camera-viewer-feasibility.md](docs/workplans/04-camera-viewer-feasibility.md).
