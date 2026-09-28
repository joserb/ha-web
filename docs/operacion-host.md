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

Las bases SQLite de los volúmenes (`notifications.sqlite3` del backend y `presence.sqlite3` de `presence`) usan WAL: las escrituras recientes viven en el fichero `-wal` hasta el siguiente checkpoint. Un `docker compose cp` del fichero principal con el servicio en marcha **no es una copia válida**. El 2026-09-28, la copia previa al despliegue de `presence` salió vacía. Copiar con la API de backup de SQLite:

```bash
docker compose exec -T presence python -c "import sqlite3; s=sqlite3.connect('/data/presence.sqlite3'); d=sqlite3.connect('/tmp/copia.sqlite3'); s.backup(d); d.close()"
docker compose cp presence:/tmp/copia.sqlite3 /opt/projects/ha-web-backups/<tema-fecha>/presence.sqlite3
docker compose exec -T presence rm /tmp/copia.sqlite3
```

Para el backend, lo mismo con `backend` y `/data/notifications.sqlite3`.

Cambiar `.env` recrea todos los servicios que lo cargan, no solo el que se quería tocar: en la práctica, backend e InfluxDB también. Los datos viven en volúmenes y sobreviven, pero cuenta con un minuto de arranque del backend.

Reiniciar el backend es seguro para el estado actual de los sensores: recupera las últimas lecturas desde InfluxDB y los retenidos que el broker reproduce al reconectar no las sobrescriben si son más antiguos. Antes del 2026-09-20 sí lo hacían, y cada reinicio dejaba todos los sensores marcados como obsoletos hasta que volvían a reportar.

## Resumen diario de Telegram (2026-09-27)

Instalado en `charo-vps`, como `joserb`, sin cambiar el backend. `scripts/daily-report.sh`
carga las credenciales Telegram del `.env` existente y ejecuta `scripts/daily_report.py`.
La entrada de cron llama cada minuto, pero Python decide cuándo enviar con
`Europe/Madrid`: **18:00**, tanto en verano como en invierno. El VPS usa UTC.
Si el host estaba apagado a esa hora, envía al volver durante ese mismo día;
no reconstruye los días perdidos.

```cron
* * * * * /opt/projects/ha-web/scripts/daily-report.sh --scheduled >> /opt/projects/ha-web/.health/daily-report.log 2>&1
```

Incluye siempre un resultado, incluso cuando todo lo comprobado está bien:

- API, InfluxDB, MQTT, puente, disponibilidad de Pi y worker de avisos.
- Contenedores de ha-web en el VPS; zro-pi, Mosquitto, Zigbee2MQTT y pasarela de cámara en la Pi.
- Supervisión reciente de la Pi, escritura/espacio libre, errores de E/S y temperatura ≥80 °C;
  disco del VPS con aviso por debajo del 10 % libre.
- Cámara: abre el WebSocket de Nginx, exige tres fragmentos de vídeo fMP4 y cierra la conexión.
  No guarda imágenes; comprueba recepción, no renderizado en un navegador.
- Los seis sensores esperados, agrupados por dispositivo. Usa las marcas temporales reales
  y los límites del catálogo: 1 h para climáticos y 24 h para puerta/vibración por defecto.
  Incluye sensores ausentes del catálogo como «sin datos».
- Batería **≤30 %** (`DAILY_REPORT_BATTERY_PERCENT`); distingue porcentajes desconocidos y
  lecturas antiguas. La fecha corresponde al mensaje del dispositivo: puede contener
  valores de batería conservados por Zigbee2MQTT de mensajes anteriores.
- Último archivo cifrado de Raspberry realmente recibido en el VPS, comprobando nombre,
  cabecera y tamaño mínimo. Avisa si falta, es inválido o tiene más de 30 h. Esto no es
  una prueba de descifrado/restauración. El informe expone las copias todavía pendientes.

Los endpoints o comprobaciones que fallan se muestran como fallo/sin datos, no como sanos.
El destino de la Pi puede cambiarse con `DAILY_REPORT_PI_URL` y el directorio de copias
con `DAILY_REPORT_BACKUP_DIR`; los valores por defecto corresponden a la instalación doméstica.

El candado `.health/daily-report.lock` evita ejecuciones simultáneas. El registro atómico
`.health/daily-report.json` guarda la fecha local y el resultado (`sent`, `rejected`,
`delivery_unknown`, etc.). Se registra el intento **antes** de enviar: una respuesta
ambigua o un proceso interrumpido no provoca mensajes duplicados. No hay reintento
automático ese día si Telegram rechaza el envío o no puede confirmarlo; revisar el log.
Un registro corrupto bloquea el envío y deja un error, para evitar duplicados.

```bash
cd /opt/projects/ha-web
scripts/daily-report.sh --preview     # comprueba sistemas; no envía Telegram
scripts/daily-report.sh --send-test   # envía una prueba; no consume el resumen de las 18:00
cat .health/daily-report.json         # existe tras el primer intento programado
python3 -m unittest discover -s scripts/tests -v
```

Telegram confirmó la entrega de la prueba el 2026-09-27. En la Raspberry se cambió
**solo** `alerts.zigbee_silence.enabled` a `false` en
`/home/joserb/zro-pi/config/pihomeblk.yaml`, y se reinició únicamente `zro-pi`.
Así se absorben los avisos individuales de silencio/recuperación en el resumen diario.
Los vigilantes de servicios, avisos de almacenamiento y controles temporales de puerta
conservan su funcionamiento. Al desplegar de nuevo el otro repositorio `zro-pi`, conservar
este ajuste doméstico: su configuración fuente anterior lo tenía a `true`.

Rollback: eliminar únicamente la línea de cron de `daily-report.sh`, restaurar
`zigbee_silence.enabled: true` en la Pi y reiniciar `zro-pi`. Se guardaron copias del
crontab anterior en `.health/crontab-before-daily-report-*` del VPS y del YAML en
`/home/joserb/zro-pi/.health/pihomeblk-before-daily-report-*.yaml` de la Pi.

## Auditoría de copias periódicas (2026-09-27)

La copia de la Raspberry **sí está implementada**: el cron de `joserb` en el VPS ejecuta
`/home/joserb/zro-pi-backup/pull-backups.sh` a las **04:17 UTC** cada día (06:17 en verano,
05:17 en invierno en Madrid). Se verificó el archivo del 27 de septiembre y el log sin
fallos. El destino es `/home/joserb/backups/zro-pi/pihomeblk/`, con cifrado age y retención
por defecto de 7 copias recientes, 4 semanas y 6 meses.

Incluye `.env` de zro-pi, contraseña de Mosquitto, directorio de datos Zigbee2MQTT
(incluido `coordinator_backup.json` y su base de dispositivos), datos persistidos de
Mosquitto y un manifiesto. La clave SSH de backup solo permite generar el snapshot.

**Cobertura parcial**: no se encontró programación para respaldar los volúmenes de
InfluxDB y notificaciones de ha-web, sus secretos/configuración ni el directorio
`camera-gateway` de la Pi. Las copias `ha-web-backups/telegram-20260918` y
`camera-20260919` son anteriores a despliegues, no una copia diaria completa.
La Raspberry tiene copia fuera de la Pi, pero no se verificó una segunda copia fuera
del VPS ni una restauración con la clave privada. El resumen diario no presenta esas
partes como protegidas.
