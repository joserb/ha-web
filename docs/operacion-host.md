# Operación en el host (VPS)

Dos ajustes viven fuera de Docker Compose y hay que aplicarlos a mano en el VPS,
una sola vez, como root. Sin ellos el stack arranca igual pero pierde dos
salvaguardas.

## 1. Bind a la IP de Tailscale antes de que Tailscale esté lista

Mosquitto y Nginx se publican en `${TS_BIND_IP}` (ver `.env.example`). Al
arrancar la máquina, Docker restaura los contenedores antes de que `tailscaled`
haya levantado la interfaz, y el bind falla: los contenedores quedan caídos y la
política `unless-stopped` no rearranca un arranque fallido.

```bash
echo 'net.ipv4.ip_nonlocal_bind = 1' > /etc/sysctl.d/99-ha-web.conf
sysctl --system
```

## 2. Vigilante del stack cada minuto

`scripts/stack-watchdog.sh` recrea un contenedor caído, sin red o `unhealthy`, y
el backend cuando `/api/health` lleva ~5 minutos en fallo. Se ejecuta en el host
a propósito: un contenedor sin red no puede diagnosticarse ni avisar desde
dentro. Usa `flock`, se detiene solo tras 3 intervenciones en una hora y anota
todo en `.health/watchdog.json`.

```bash
crontab -e
# * * * * * /opt/projects/ha-web/scripts/stack-watchdog.sh >> /var/log/ha-web-watchdog.log 2>&1
```

Para trabajar a mano sin que estorbe:

```bash
touch /opt/projects/ha-web/.health/watchdog-pausa   # y borrarlo al terminar
```

Las alertas de Telegram son opcionales: si `TELEGRAM_BOT_TOKEN` y
`TELEGRAM_CHAT_ID` no están en `.env`, el vigilante sigue actuando y solo deja
de avisar.


## Avisos temporales de puerta

El backend mantiene las reglas y la cola Telegram en el volumen Compose `notification-data` (`/data/notifications.sqlite3`). No usar `docker compose down -v` para actualizar el stack: eliminaría también este estado. El fichero es SQLite con WAL; para obtener una copia coherente con el servicio activo, usar la API de backup de SQLite, no copiar únicamente el fichero principal.

`/api/health` incluye `notification_worker_running` y devuelve 503 si el worker termina inesperadamente. El vigilante puede recuperar el backend en ese caso. Las reglas conservan su fecha original de vencimiento; arrancar no las prolonga ni activa reglas nuevas.

Los avisos usan `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` del `.env`, compartidos con el vigilante. La presencia de ambas variables habilita el control; la entrega real requiere además que el bot tenga acceso al chat. Los errores se muestran en la tarjeta sin revelar credenciales.

Despliegue del 2026-09-18: fuentes anteriores guardadas en `/opt/projects/ha-web-backups/telegram-20260918/source-before.tgz`; imágenes anteriores `ha-web-backend:before-telegram-20260918` y `ha-web-nginx:before-telegram-20260918`. El rollback puede restaurar estas fuentes e imágenes conservando todos los volúmenes. El frontend anterior no muestra el control; desactivar cualquier regla activa antes de volver a la versión anterior.


## Pasarela de cámara

La pasarela go2rtc corre en `pihomeblk-1`, no en el VPS: `camera-gateway/` tiene su propio Compose y su [guía de despliegue](../camera-gateway/README.md). Detenerla o recrearla no toca zro-pi, Zigbee2MQTT, Mosquitto, InfluxDB ni el backend.

En el VPS, la ruta de vídeo depende de dos variables del `.env`: `CAMERA_ENABLED` y `CAMERA_GATEWAY_HOSTPORT`. Se aplican al recrear el contenedor `nginx` (`docker compose up -d nginx`), porque la plantilla se procesa con envsubst al arrancar. Con `CAMERA_ENABLED=false`, `/camera/config.json` devuelve `{"enabled": false}`, el dashboard no monta la tarjeta y la ruta de reproducción apunta a un destino inexistente: es el estado de reversión y también el valor por defecto.

`/camera/home/ws` no atraviesa FastAPI, así que una pasarela caída no afecta a `/api/health` ni al vigilante del stack. Al revés también: el vídeo sigue disponible aunque falle la API de sensores.

Comprobar desde el VPS que solo la ruta de reproducción está expuesta, sustituyendo la IP Tailscale de la Pi:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://IP_PI:1984/api/streams   # 404 esperado
curl -s -o /dev/null -w '%{http_code}\n' http://IP_PI:1984/api/ws        # 400 esperado
```


## Actualizar el stack desde GitHub

El VPS se actualiza con `git pull`, pero **no tiene clave propia para GitHub**: hay que entrar reenviando el agente SSH desde el equipo que sí la tiene.

```bash
# en el equipo de desarrollo
eval "$(ssh-agent -s)" && ssh-add ~/.ssh/github_joserb
ssh -A charo-vps
# en el VPS
cd /opt/projects/ha-web && git pull --ff-only
docker compose up -d --build nginx      # o backend, según lo que cambie
```

Alternativa permanente: una deploy key de solo lectura en el VPS. No está configurada.

Antes de cada despliegue conviene guardar los fuentes y etiquetar la imagen anterior, como se hizo en `/opt/projects/ha-web-backups/<tema-fecha>/` e `ha-web-nginx:before-<tema>-<fecha>`; permite volver atrás sin depender de Git.

Cambiar `.env` recrea todos los servicios que lo cargan, no solo el que se quería tocar: en la práctica, backend e InfluxDB también. Los datos viven en volúmenes y sobreviven, pero cuenta con un minuto de arranque del backend.

Reiniciar el backend es seguro para el estado actual de los sensores: recupera las últimas lecturas desde InfluxDB y los retenidos que el broker reproduce al reconectar no las sobrescriben si son más antiguos. Antes del 2026-09-20 sí lo hacían, y cada reinicio dejaba todos los sensores marcados como obsoletos hasta que volvían a reportar.
