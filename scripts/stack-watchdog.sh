#!/usr/bin/env bash
# Vigilante del stack ha-web. Se ejecuta EN EL HOST (cron, cada minuto; ver
# docs/operacion-host.md) porque los fallos que persigue son exactamente los que
# desde dentro del contenedor no se ven ni se pueden arreglar.
#
# Qué mira, en orden:
#   a) un contenedor del proyecto en 'exited' —la política unless-stopped NO
#      rearranca un arranque fallido al restaurar el estado tras un reinicio— o
#      en 'running' pero sin red (NetworkSettings.Networks == {}, la firma del
#      incidente del 2026-08-08 en la Pi hermana: el broker entregaba los
#      mensajes y nadie los escuchaba);
#   b) un contenedor 'unhealthy';
#   c) el backend arriba pero con /api/health en 503 durante 5 comprobaciones
#      seguidas (~5 min): sin broker o sin InfluxDB el dashboard no sirve de
#      nada aunque el proceso siga en pie.
#
# La cura es siempre la misma y es la comprobada a mano:
#   docker compose up -d --force-recreate <servicio>
#
# Se avisa por Telegram desde el host a propósito: cuando el contenedor está sin
# red, nada de dentro puede hablar con nadie, así que esta es la única fuente de
# aviso posible para ese fallo.
#
# Cada intervención queda en .health/watchdog.json (JSON válido siempre,
# escritura atómica).
#
# Para trabajar a mano sin que el vigilante estorbe: touch .health/watchdog-pausa
set -uo pipefail
cd "$(dirname "$0")/.." || exit 0

# cron arranca con un PATH mínimo (/usr/bin:/bin); docker compose puede estar en
# /usr/local/bin según cómo se instalara.
export PATH="$PATH:/usr/local/bin:/usr/sbin:/sbin"

mkdir -p .health

# Un solo vigilante a la vez: la cura tarda más de un minuto en el peor caso y
# dos ejecuciones de cron solapadas se pisarían entre ellas. Sirve además de
# candado frente a un 'docker compose up' manual que use el mismo fichero.
exec 9>.health/watchdog.lock
flock -n 9 || exit 0

# Mano humana trabajando: no tocar nada (un contenedor parado a propósito no es
# una avería).
[ -f .health/watchdog-pausa ] && exit 0

if [ -f .env ]; then
    # shellcheck disable=SC1091
    set -a; source ./.env; set +a
fi

# El backend se publica en localhost; Nginx hace de proxy, pero se sondea al
# backend directamente para no confundir "backend caído" con "nginx caído".
SONDA_URL="http://127.0.0.1:8000/api/health"
SERVICIO_SONDA=backend
CONTADOR=.health/watchdog-salud.count
MARCAS=.health/watchdog-marcas
AVISO_LIMITE=.health/watchdog-limite
REGISTRO=.health/watchdog.json
MAX_POR_HORA=3         # tope de intervenciones por hora (anti-flapping)
FALLOS_SALUD=5         # comprobaciones seguidas en 503 antes de intervenir
MAQUINA=$(hostname 2>/dev/null || echo vps)

avisar() {
    echo "$1"
    [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || return 0
    curl -fsS -m 15 -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=$1" >/dev/null \
        || echo "  (no se pudo enviar la alerta a Telegram)" >&2
}

# Sano = HTTP 200 exacto. El endpoint responde 503 cuando falta el broker o
# InfluxDB, así que no hace falta leer el cuerpo.
sano() {
    local codigo
    codigo=$(curl -fsS --max-time 5 -o /dev/null -w '%{http_code}' "$SONDA_URL" 2>/dev/null || true)
    [ "$codigo" = 200 ]
}

# Contenedores de ESTE proyecto compose. El filtro por working_dir no depende de
# cómo se llame el directorio ni del proyecto vecino (OpenClaw) del mismo VPS.
LISTA=$(docker ps -a --filter "label=com.docker.compose.project.working_dir=$PWD" \
    --format '{{.Names}}	{{.Label "com.docker.compose.service"}}	{{.State}}' 2>/dev/null || true)
# Sin contenedores no hay nada que vigilar (docker parado, stack sin arrancar o
# un 'docker compose down' deliberado): callar es lo correcto.
[ -n "$LISTA" ] || exit 0

estado_de() {   # servicio -> estado del contenedor ('' si no existe)
    printf '%s\n' "$LISTA" | awk -F'\t' -v s="$1" '$2 == s {print $3; exit}'
}

servicio=""
motivo=""

# (a) caído o sin red -----------------------------------------------------
while IFS=$'\t' read -r nombre serv estado; do
    [ -n "$nombre" ] && [ -n "$serv" ] || continue
    case "$estado" in
        exited|dead)
            servicio=$serv
            motivo="el contenedor $nombre está $estado (la política de reinicio no rearranca un arranque fallido)"
            break
            ;;
        running)
            redes=$(docker inspect --format '{{json .NetworkSettings.Networks}}' "$nombre" 2>/dev/null || true)
            if [ "$redes" = "{}" ]; then
                servicio=$serv
                motivo="el contenedor $nombre corre sin red (Networks vacío)"
                break
            fi
            ;;
    esac
done <<EOF
$LISTA
EOF

# (b) unhealthy -----------------------------------------------------------
if [ -z "$servicio" ]; then
    while IFS=$'\t' read -r nombre serv estado; do
        [ "$estado" = running ] || continue
        salud=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
            "$nombre" 2>/dev/null || true)
        if [ "$salud" = unhealthy ]; then
            servicio=$serv
            motivo="el contenedor $nombre está unhealthy"
            break
        fi
    done <<EOF
$LISTA
EOF
fi

# (c) backend vivo pero enfermo -------------------------------------------
# Con paciencia a propósito: un reinicio del broker, una recarga de InfluxDB o
# un arranque en curso devuelven 503 un rato y eso no es una avería.
if [ -z "$servicio" ] && [ "$(estado_de "$SERVICIO_SONDA")" = running ]; then
    if sano; then
        echo 0 > "$CONTADOR"
    else
        fallos=$(( $(cat "$CONTADOR" 2>/dev/null || echo 0) + 1 ))
        echo "$fallos" > "$CONTADOR"
        if [ "$fallos" -ge "$FALLOS_SALUD" ]; then
            servicio=$SERVICIO_SONDA
            motivo="el backend lleva $fallos comprobaciones respondiendo /api/health en fallo"
            echo 0 > "$CONTADOR"
        fi
    fi
fi

[ -n "$servicio" ] || exit 0

# --- registro ------------------------------------------------------------
registrar() {   # servicio motivo accion resultado intervenciones_ultima_hora
    REG_SERVICIO=$1 REG_MOTIVO=$2 REG_ACCION=$3 REG_RESULTADO=$4 \
    REG_RECIENTES=$5 REG_FICHERO=$REGISTRO REG_MAQUINA=$MAQUINA \
    python3 - <<'PY' || true
import json
import os
import tempfile
from datetime import datetime, timezone

entorno = os.environ
destino = entorno["REG_FICHERO"]

anotacion = {
    "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "host": entorno["REG_MAQUINA"],
    "service": entorno["REG_SERVICIO"],
    "reason": entorno["REG_MOTIVO"],
    "action": entorno["REG_ACCION"],
    "result": entorno["REG_RESULTADO"],
}

# El histórico previo es informativo: si el fichero está corrupto se empieza de
# cero antes que perder la anotación de ahora.
historico = []
try:
    with open(destino, encoding="utf-8") as fichero:
        historico = json.load(fichero).get("history") or []
except Exception:
    historico = []

registro = {
    "generated_at": anotacion["timestamp_utc"],
    "last": anotacion,
    "interventions_last_hour": int(entorno.get("REG_RECIENTES") or 0),
    "history": ([anotacion] + historico)[:20],
}

directorio = os.path.dirname(destino) or "."
descriptor, temporal = tempfile.mkstemp(dir=directorio, prefix=".watchdog.json.")
try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as fichero:
        json.dump(registro, fichero)
        fichero.write("\n")
    os.chmod(temporal, 0o644)
    os.replace(temporal, destino)  # atómico: el lector nunca ve medio JSON
except Exception:
    os.unlink(temporal)
    raise
PY
}

# --- anti-flapping -------------------------------------------------------
# Un stack que se recrea sin parar no se está curando: se está rompiendo de otra
# manera. Pasado el tope, el vigilante deja de tocar y solo avisa.
ahora=$(date +%s)
awk -v limite=$((ahora - 3600)) '$1+0 >= limite {print $1}' "$MARCAS" 2>/dev/null > "$MARCAS.tmp" || true
mv "$MARCAS.tmp" "$MARCAS" 2>/dev/null || true
recientes=$(grep -c . "$MARCAS" 2>/dev/null || true)
recientes=${recientes:-0}

if [ "$recientes" -ge "$MAX_POR_HORA" ]; then
    # El aviso se repite como mucho una vez por hora: con cron cada minuto, si no
    # se acaba ignorando el canal entero.
    if [ -z "$(find "$AVISO_LIMITE" -newermt '-1 hour' 2>/dev/null)" ]; then
        touch "$AVISO_LIMITE"
        avisar "🚨 ha-web ($MAQUINA): $motivo. Ya van $recientes recreaciones en la última hora, el vigilante se detiene. Hace falta mirarlo a mano."
    else
        echo "límite anti-flapping alcanzado ($recientes/h); sin intervenir: $motivo"
    fi
    registrar "$servicio" "$motivo" "ninguna (límite anti-flapping)" "detenido" "$recientes"
    exit 1
fi

# --- cura ----------------------------------------------------------------
echo "$ahora" >> "$MARCAS"
avisar "⚠️ ha-web ($MAQUINA): $motivo. Recreando el contenedor de '$servicio'."

if docker compose up -d --force-recreate "$servicio" >/dev/null 2>&1; then
    accion="docker compose up -d --force-recreate $servicio"
    resultado=sin_recuperar
    # ~1 min de margen: el backend arranca, recupera estado, conecta al broker y
    # recibe los retenidos antes de que /api/health devuelva 200.
    for _ in 1 2 3 4 5 6; do
        sleep 10
        if sano; then
            resultado=recuperado
            break
        fi
    done
    if [ "$resultado" = recuperado ]; then
        echo "recuperado tras recrear $servicio"
        echo 0 > "$CONTADOR"
    else
        avisar "🚨 ha-web ($MAQUINA): tras recrear '$servicio' /api/health sigue en fallo. Hace falta mirarlo a mano."
    fi
else
    accion="docker compose up -d --force-recreate $servicio (falló)"
    resultado=error
    avisar "🚨 ha-web ($MAQUINA): falló la recreación de '$servicio'. Hace falta mirarlo a mano."
fi

registrar "$servicio" "$motivo" "$accion" "$resultado" "$((recientes + 1))"
[ "$resultado" = recuperado ]
