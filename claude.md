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
- `GET /api/history?location=...&measurement=...&hours=24` — Histórico numérico agregado en ventanas de 5min (media)
- `GET /api/events?location=...&measurement=...&hours=24` — Eventos individuales sin agregar (estado string, ej: puerta open/closed)
- `WS /ws` — WebSocket bidireccional: recibe datos en tiempo real, envía comandos MQTT

## Estructura de topics MQTT

- Formato: `home/{ubicacion}/{medida}` (ej: `home/salon/temp`)
- Payload JSON: `{"value": 22.5}` o valores simples
- El backend parsea el topic para extraer tags `location` y `measurement` en InfluxDB
- Payloads numéricos → field `value` (float)
- Payloads string (ej: "open"/"closed") → field `state` (string)
- Payloads JSON → cada clave numérica se escribe como field propio

## Frontend

- Dashboard modular: HTML + CSS + JS (ES modules, sin framework ni build step)
- Estructura: `frontend/index.html`, `frontend/css/styles.css`, `frontend/js/{app,sensors,ui}.js`
- Gauge.js via CDN para indicadores de temperatura semicirculares
- Chart.js via CDN para gráfica de tendencia (últimas 24h) dentro de cada card de temp
- Sensor registry en `sensors.js`: añadir nuevo tipo de sensor = añadir entrada al registro
- Tipos implementados: `temp` (gauge + sparkline Chart.js), `door` (binario + historial pares open/close)
- Iconos SVG inline (termómetro, puerta abierta, puerta cerrada)
- WebSocket con reconexión automática (3s), filtra topic `/test`
- Al conectar, el backend envía últimos valores conocidos (replay de `last_messages`)
- `sendCommand()` exportada en `app.js` para futuro panel de comandos/actuadores
- Historial de puerta: carga `/api/events` al crear card, añade eventos en tiempo real, agrupa en pares open→close
- Dark theme responsive (CSS Grid)

## Configuración sensible

- Todo en `.env` (nunca en Git)
- Variables: MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASSWORD, INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET, INFLUXDB_USER, INFLUXDB_PASSWORD

## Esquema InfluxDB

- Measurement: `sensor`
- Tags: `location` (ej: `home/salon`), `measurement` (ej: `temp`)
- Fields: `value` (float, sensores numéricos), `state` (string, sensores de estado)
- Query de `/api/history` tiene retrocompatibilidad: acepta tanto field `value` con tag `measurement`, como field con nombre igual al measurement (esquema antiguo)

## Próximos pasos

1. Panel de actuadores (control de luces/enchufes vía MQTT bidireccional)
2. Integración con Moltbot (disparar acciones desde la web)
3. Añadir más tipos de sensor (humedad, CO2, etc.)