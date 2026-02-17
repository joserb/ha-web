# CLAUDE.md — Contexto del proyecto ha-web

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

- VPS y RPi (Home Assistant) están en la misma red Tailscale
- PC Windows de desarrollo también en Tailscale
- MQTT accesible vía Tailscale para HA y herramientas como MQTT Studio

## Home Assistant (RPi)

- Instalación: HAOS (Home Assistant OS)
- Tailscale instalado y conectado
- Integración MQTT configurada apuntando al broker del VPS vía Tailscale
- Automatizaciones activas publicando sensores: temp (salon, terraza, habitacion, estudio), door (entrada)
- Topic `/test` reservado para pruebas de conexión (no se almacena ni se grafica)

## Endpoints API

- `GET /api/health` — Estado del backend y topics activos
- `GET /api/history/{location}/{measurement}?hours=24` — Histórico de sensor desde InfluxDB (agregado en ventanas de 5min)
- `WS /ws` — WebSocket bidireccional: recibe datos en tiempo real, envía comandos MQTT

## Estructura de topics MQTT

- Formato: `home/{ubicacion}/{medida}` (ej: `home/salon/temp`)
- Payload JSON: `{"value": 22.5}` o valores simples
- El backend parsea el topic para extraer tags location/measurement en InfluxDB

## Frontend

- Dashboard modular: HTML + CSS + JS (ES modules, sin framework ni build step)
- Estructura: `frontend/index.html`, `frontend/css/styles.css`, `frontend/js/{app,sensors,ui}.js`
- Gauge.js via CDN para indicadores de temperatura semicirculares
- Sensor registry en `sensors.js`: añadir nuevo tipo de sensor = añadir entrada al registro
- Tipos implementados: `temp` (gauge), `door` (binario abierta/cerrada)
- WebSocket con reconexión automática, filtra topic `/test`
- `sendCommand()` exportada en `app.js` para futuro panel de comandos
- Dark theme responsive (CSS Grid)
- Pendiente: gráficas de tendencias (Chart.js), panel de comandos/actuadores

## Configuración sensible

- Todo en `.env` (nunca en Git)
- Variables: MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASSWORD, INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET, INFLUXDB_USER, INFLUXDB_PASSWORD

## Próximos pasos

1. Mejorar dashboard con gráficas de tendencias (Chart.js)
2. Añadir actuadores (control de luces vía MQTT bidireccional)
3. Integración con Moltbot (disparar acciones desde la web)