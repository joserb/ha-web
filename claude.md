# CLAUDE.md — Contexto del proyecto ha-web

## Entorno de ejecución

- **VPS**: Hetzner Cloud, Ubuntu Server
- **Acceso**: SSH (claves), Tailscale disponible
- **Firewall**: Configurado, sin puertos públicos innecesarios
- **Desarrollo**: VS Code Remote-SSH desde Windows (claves copiadas desde WSL)
- **Repo**: git@github.com:joserb/ha-web.git

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

## Stack ha-web

- **Mosquitto**: Broker MQTT para telemetría domótica
- **FastAPI**: Backend Python asíncrono (MQTT + WebSocket + REST)
- **Nginx**: Frontend estático + reverse proxy al backend
- **Docker Compose**: Orquestación de los tres servicios
- Todos los puertos ligados a 127.0.0.1 (sin exposición pública)

## Convenciones

- Toda la configuración sensible va en `.env` (nunca en Git)
- Los servicios solo se exponen internamente; acceso externo vía Tailscale o port forwarding
- El frontend se comunica con el backend por WebSocket para datos en tiempo real