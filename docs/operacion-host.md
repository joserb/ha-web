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
