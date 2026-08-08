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
