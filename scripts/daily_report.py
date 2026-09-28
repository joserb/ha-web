#!/usr/bin/env python3
"""Daily home report, run on the VPS host. Python standard library only.

Cron calls --scheduled every minute; Europe/Madrid selects the due date/time.
An atomic journal and flock prevent duplicate sends, including ambiguous timeouts.
No Telegram URLs, credentials or provider error bodies are logged.
"""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo("Europe/Madrid")
EXPECTED = {"bano": "Baño", "estudio": "Estudio", "habitacion": "Habitación",
            "terraza": "Terraza", "entrada": "Entrada", "comedero-gatos": "Comedero"}
PI_CONTAINERS = {"zro-pi-zro-pi-1", "zro-pi-mosquitto-1", "zro-pi-zigbee2mqtt-1",
                 "ha-web-camera-gateway"}
VPS_CONTAINERS = {f"ha-web-{s}-1" for s in ("nginx", "backend", "mosquitto", "influxdb")}


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def age(timestamp, now):
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        delta = (now - dt).total_seconds()
        return max(0, delta) if delta >= -300 else None
    except (ValueError, TypeError, AttributeError):
        return None


def duration(seconds):
    if seconds >= 86400:
        return f"{seconds / 86400:.1f} días"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} h"
    return f"{seconds / 60:.0f} min"


def get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # /api/health intentionally returns useful JSON with HTTP 503.
        try:
            return json.loads(exc.read(65536))
        except (ValueError, OSError):
            return None
    except Exception:
        return None


def check_containers(containers, expected):
    rows = {c.get("name"): c for c in containers}
    bad = []
    for name in sorted(expected):
        c = rows.get(name, {})
        if c.get("status") != "running" or c.get("health") not in (None, "", "healthy"):
            bad.append(name)
    return bad


def sensor_report(rows, now, threshold=30):
    grouped = {}
    for row in rows:
        name = row.get("location", "").removeprefix("home/")
        grouped.setdefault(name, []).append(row)
    missing, low, batteries = [], [], []
    fresh_count = 0
    for name in sorted(set(EXPECTED) | set(grouped)):
        label = EXPECTED.get(name, name)
        channels = grouped.get(name, [])
        readings = [(r, age((r.get("current") or {}).get("updated_at"), now)) for r in channels]
        ages = [a for _, a in readings if a is not None]
        # One device, one silence warning, even when it exposes four channels.
        limit = max((number(r.get("stale_after_seconds")) or 3600 for r in channels), default=3600)
        if not ages:
            missing.append(f"{label}: sin datos")
        elif min(ages) > limit:
            missing.append(f"{label}: {duration(min(ages))} sin reportar")
        else:
            fresh_count += 1
        battery = next(((r, a) for r, a in readings if r.get("measurement") == "battery"), None)
        value = number(((battery[0].get("current") or {}).get("payload"))) if battery else None
        if value is None or not 0 <= value <= 100 or not battery or battery[1] is None:
            batteries.append(f"{label}: sin porcentaje disponible")
        else:
            old = battery[1] > (number(battery[0].get("stale_after_seconds")) or limit)
            suffix = f" (lectura de hace {duration(battery[1])})" if old else ""
            batteries.append(f"{label}: {value:g}%{suffix}")
            if value <= threshold:
                low.append(f"{label}: {value:g}%{suffix}")
    return fresh_count, len(set(EXPECTED) | set(grouped)), missing, low, batteries


CAMERA_PROBE = '''
import asyncio,json,websockets
async def run():
    async with websockets.connect("ws://nginx/camera/home/ws",open_timeout=6,close_timeout=2,max_size=4000000) as ws:
        await ws.send(json.dumps({"type":"mse","value":"avc1.640029,avc1.64002A,avc1.640033,mp4a.40.2,mp4a.40.5"}))
        fragments=0
        while fragments<3:
            msg=await ws.recv()
            if isinstance(msg,bytes) and b"mdat" in msg:
                fragments+=1
            elif isinstance(msg,str) and json.loads(msg).get("type")=="error":
                raise RuntimeError("stream unavailable")
try:
    asyncio.run(asyncio.wait_for(run(),15))
    print("video_ok")
except Exception:
    print("video_unavailable")
'''


def collect():
    health = get_json("http://127.0.0.1:8080/api/health")
    sensors = get_json("http://127.0.0.1:8080/api/sensors")
    pi = get_json(os.getenv("DAILY_REPORT_PI_URL", "http://100.120.246.118:8081/api/status"))
    try:
        proc = subprocess.run(["docker", "inspect", *sorted(VPS_CONTAINERS)],
                              capture_output=True, text=True, timeout=10)
        containers = [{"name": c["Name"].lstrip("/"), "status": c["State"]["Status"],
                       "health": c["State"].get("Health", {}).get("Status")}
                      for c in json.loads(proc.stdout)] if proc.returncode == 0 else []
    except Exception:
        containers = []
    try:
        probe = subprocess.run(["docker", "exec", "ha-web-backend-1", "python", "-c", CAMERA_PROBE],
                               capture_output=True, text=True, timeout=22)
        camera = probe.returncode == 0 and probe.stdout.strip() == "video_ok"
    except Exception:
        camera = False
    backup_dir = Path(os.getenv("DAILY_REPORT_BACKUP_DIR", "/home/joserb/backups/zro-pi/pihomeblk"))
    backups = sorted(backup_dir.glob("*.tar.age"))
    backup = None
    if backups:
        try:
            path = backups[-1]
            with path.open("rb") as handle:
                valid = handle.read(21).startswith(b"age-encryption.org/v1")
            backup = {"time": datetime.strptime(path.stem.removesuffix(".tar"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat(),
                      "valid": valid and path.stat().st_size >= 1024}
        except (OSError, ValueError):
            pass
    disk = shutil.disk_usage(ROOT)
    return {"health": health, "sensors": sensors, "pi": pi, "containers": containers,
            "camera": camera, "backup": backup, "disk_free_pct": disk.free / disk.total * 100}


def build_report(data, now, threshold=30):
    problems, lines = [], []
    health = data.get("health") or {}
    for key, label in (("mqtt_connected", "MQTT VPS"), ("influxdb_connected", "InfluxDB"),
                       ("notification_worker_running", "Servicio de avisos"), ("bridge_connected", "Puente MQTT")):
        if health.get(key) is not True:
            problems.append(f"{label}: fallo o estado no disponible")
    if health.get("status") != "healthy" or health.get("pi_availability") != "online":
        problems.append("API o disponibilidad de Raspberry: revisar")
    bad = check_containers(data.get("containers", []), VPS_CONTAINERS)
    if bad:
        problems.append("Servicios VPS: " + ", ".join(bad))
    if data.get("disk_free_pct", 0) < 10:
        problems.append("Disco VPS: menos del 10% libre")
    pi = data.get("pi") or {}
    system = pi.get("system") or {}
    pi_age = age(pi.get("generated_at"), now)
    sys_age = age(system.get("generated_at"), now)
    if pi_age is None or pi_age > 180 or (pi.get("service") or {}).get("mqtt_connected") is not True:
        problems.append("Raspberry/zro-pi: sin estado reciente o MQTT desconectado")
    if sys_age is None or sys_age > 180:
        problems.append("Supervisión del host Raspberry: sin datos recientes")
    else:
        bad = check_containers((system.get("docker") or {}).get("containers", []), PI_CONTAINERS)
        if bad:
            problems.append("Servicios Raspberry: " + ", ".join(bad))
        storage = system.get("storage") or {}
        if storage.get("readonly") is not False or (number(storage.get("free_pct")) or 0) < 10:
            problems.append("Almacenamiento Raspberry: revisar escritura/espacio")
        if (number(storage.get("io_errors")) or 0) > 0:
            problems.append("Raspberry: errores de E/S registrados")
        if (number((system.get("host") or {}).get("temp_c")) or 0) >= 80:
            problems.append("Raspberry: temperatura de 80 °C o superior")
    if (pi.get("health") or {}).get("storage") != "ok":
        problems.append("Comprobación de escritura Raspberry: fallo o sin datos")
    lines.append("Cámara: " + ("vídeo recibido ✅" if data.get("camera") else "sin vídeo verificable ⚠️"))
    if not data.get("camera"):
        problems.append("Cámara: no se han recibido fragmentos de vídeo")
    backup = data.get("backup") or {}
    backup_age = age(backup.get("time"), now)
    if backup.get("valid") and backup_age is not None and backup_age <= 30 * 3600:
        lines.append(f"Backup Raspberry en VPS: recibido hace {duration(backup_age)} ✅")
    else:
        problems.append("Backup Raspberry: ausente, inválido o con más de 30 h")
    # Explicit scope: a Pi snapshot is not a backup of the whole installation.
    lines.append("Copias pendientes: histórico/configuración ha-web y configuración de cámara sin backup periódico.")
    rows = data.get("sensors")
    if not isinstance(rows, list):
        problems.append("Sensores: API no disponible")
        rows = []
    fresh, total, missing, low, batteries = sensor_report(rows, now, threshold)
    lines.append(f"Sensores con datos recientes: {fresh}/{total}")
    problems.extend(missing)
    problems.extend("Batería baja: " + item for item in low)
    lines.append(f"Baterías (aviso ≤{threshold:g}%): " + "; ".join(batteries))
    header = f"🏠 Casa · {now.astimezone(ZONE):%d/%m/%Y %H:%M}"
    verdict = "⚠️ Hay incidencias:" if problems else "✅ Servicios y sensores comprobados: correctos."
    # Budget by sections, keeping health issues first. Telegram's 4096 limit
    # uses UTF-16 code units, so 3500 characters leaves room for emoji.
    result = "\n".join([header, verdict, *("• " + p for p in problems), "", *lines])
    if len(result) > 3500:
        result = result[:3420] + "\n… Resumen recortado; revisar dashboard para el detalle."
    return result


def due(now, state):
    local = now.astimezone(ZONE)
    return local.hour >= 18 and state.get("date") != local.date().isoformat()


def save_state(path, data):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".daily-report-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def send(message):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return "not_configured"
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": chat, "text": message}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return "sent" if json.load(response).get("ok") is True else "rejected"
    except urllib.error.HTTPError:
        return "rejected"
    except Exception:
        return "delivery_unknown"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scheduled", action="store_true")
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--send-test", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    directory = ROOT / ".health"
    directory.mkdir(exist_ok=True)
    with (directory / "daily-report.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        now = datetime.now(timezone.utc)
        path = directory / "daily-report.json"
        try:
            state = json.loads(path.read_text())
            if not isinstance(state, dict):
                raise ValueError("invalid journal")
        except FileNotFoundError:
            state = {}
        except (ValueError, OSError):
            print("daily-report: journal unreadable; refusing duplicate send")
            return 1
        if args.scheduled and not due(now, state):
            return 0
        threshold = number(os.getenv("DAILY_REPORT_BATTERY_PERCENT", "30"))
        if threshold is None or not 0 <= threshold <= 100:
            print("daily-report: invalid battery threshold")
            return 1
        report = build_report(collect(), now, threshold)
        if args.preview:
            print(report)
            return 0
        if args.scheduled:
            state = {"date": now.astimezone(ZONE).date().isoformat(), "status": "sending",
                     "attempted_at": now.isoformat()}
            save_state(path, state)
        status = send(("🧪 Prueba del resumen diario\n" if args.send_test else "") + report)
        if args.scheduled:
            state["status"] = status
            save_state(path, state)
        print("daily-report:", status)
        return 0 if status == "sent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
