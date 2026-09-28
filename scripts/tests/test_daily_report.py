import importlib.util
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("daily_report", Path(__file__).parents[1] / "daily_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
NOW = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)


def row(name, measurement="temp", value="22", hours=0.1, limit=3600):
    return {"location": "home/" + name, "measurement": measurement,
            "stale_after_seconds": limit, "current": {
                "payload": value, "updated_at": (NOW - timedelta(hours=hours)).isoformat()}}


def healthy():
    rows = [row(name, limit=86400 if name in ("entrada", "comedero-gatos") else 3600)
            for name in report.EXPECTED]
    rows += [row(name, "battery", "80") for name in report.EXPECTED if name != "comedero-gatos"]
    return {"health": {"status": "healthy", "pi_availability": "online", "mqtt_connected": True,
                       "influxdb_connected": True, "bridge_connected": True, "notification_worker_running": True},
            "sensors": rows, "camera": True, "disk_free_pct": 50,
            "containers": [{"name": n, "status": "running", "health": "healthy"} for n in report.VPS_CONTAINERS],
            "backup": {"valid": True, "time": (NOW - timedelta(hours=12)).isoformat()},
            "pi": {"generated_at": NOW.isoformat(), "service": {"mqtt_connected": True},
                   "health": {"storage": "ok"}, "system": {"generated_at": NOW.isoformat(),
                       "storage": {"readonly": False, "free_pct": 50, "io_errors": 0},
                       "host": {"temp_c": 65},
                       "docker": {"containers": [{"name": n, "status": "running", "health": None}
                                                   for n in report.PI_CONTAINERS]}}}}


class SensorTests(unittest.TestCase):
    def test_silence_is_once_per_device_and_missing_inventory_counts(self):
        rows = [row("terraza", m, hours=4) for m in ("temp", "humidity", "pressure", "battery")]
        fresh, total, missing, _, _ = report.sensor_report(rows, NOW)
        self.assertEqual((fresh, total), (0, 6))
        self.assertEqual(sum(s.startswith("Terraza:") for s in missing), 1)
        self.assertIn("Habitación: sin datos", missing)

    def test_event_sensor_uses_own_silence_limit(self):
        rows = [row("entrada", "door", "closed", hours=12, limit=86400), row("terraza", hours=12)]
        fresh, _, missing, _, _ = report.sensor_report(rows, NOW)
        self.assertEqual(fresh, 1)
        self.assertFalse(any(s.startswith("Entrada:") for s in missing))

    def test_battery_inclusive_threshold_and_unknown_and_stale(self):
        rows = [row("bano", "battery", "30"), row("terraza", "battery", "31"),
                row("habitacion", "battery", "nan"), row("estudio", "battery", "15", hours=4)]
        _, _, _, low, batteries = report.sensor_report(rows, NOW)
        self.assertIn("Baño: 30%", low)
        self.assertFalse(any(s.startswith("Terraza:") for s in low))
        self.assertIn("Habitación: sin porcentaje disponible", batteries)
        self.assertTrue(any("Estudio: 15% (lectura de hace 4.0 h)" == s for s in low))

    def test_bad_timestamps_and_battery_ranges_are_unknown(self):
        rows = [row("bano", "battery", "101")]
        rows[0]["current"]["updated_at"] = "invalid"
        fresh, _, missing, low, batteries = report.sensor_report(rows, NOW)
        self.assertEqual(fresh, 0)
        self.assertEqual(low, [])
        self.assertIn("Baño: sin datos", missing)
        self.assertIn("Baño: sin porcentaje disponible", batteries)


class ReportTests(unittest.TestCase):
    def test_healthy_includes_backup_scope_and_unknown_battery(self):
        text = report.build_report(healthy(), NOW)
        self.assertIn("Servicios y sensores comprobados: correctos", text)
        self.assertIn("6/6", text)
        self.assertIn("Comedero: sin porcentaje disponible", text)
        self.assertIn("sin backup periódico", text)

    def test_outage_does_not_look_healthy(self):
        text = report.build_report({}, NOW)
        self.assertIn("Hay incidencias", text)
        self.assertIn("Sensores: API no disponible", text)
        self.assertIn("Cámara: no se han recibido", text)
        self.assertNotIn("comprobados: correctos", text)

    def test_missing_zigbee_container_and_stale_snapshot(self):
        data = healthy()
        data["pi"]["system"]["docker"]["containers"] = []
        text = report.build_report(data, NOW)
        self.assertIn("zro-pi-zigbee2mqtt-1", text)
        data["pi"]["system"]["generated_at"] = (NOW - timedelta(minutes=10)).isoformat()
        self.assertIn("Supervisión del host Raspberry: sin datos recientes", report.build_report(data, NOW))

    def test_old_backup_and_camera_failure(self):
        data = healthy()
        data["backup"]["time"] = (NOW - timedelta(hours=31)).isoformat()
        data["camera"] = False
        text = report.build_report(data, NOW)
        self.assertIn("más de 30 h", text)
        self.assertIn("Cámara: no se han recibido", text)

    def test_message_size(self):
        data = healthy()
        data["sensors"] = [row("device" + str(n), hours=10) for n in range(100)]
        self.assertLess(len(report.build_report(data, NOW).encode("utf-16-le")) // 2, 4096)


class ScheduleTests(unittest.TestCase):
    def test_summer_18_madrid_is_16_utc(self):
        self.assertFalse(report.due(NOW - timedelta(minutes=1), {}))
        self.assertTrue(report.due(NOW, {}))
        self.assertFalse(report.due(NOW, {"date": "2026-09-27", "status": "sent"}))

    def test_winter_and_dst_transition(self):
        for month, day in [(10, 25), (12, 1)]:
            before = datetime(2026, month, day, 16, 59, tzinfo=timezone.utc)
            self.assertFalse(report.due(before, {}))
            self.assertTrue(report.due(before + timedelta(minutes=1), {}))

    def test_catchup_and_unknown_delivery_never_duplicate(self):
        self.assertTrue(report.due(NOW + timedelta(hours=2), {"date": "2026-09-26"}))
        for status in ("sending", "delivery_unknown", "rejected", "sent"):
            self.assertFalse(report.due(NOW, {"date": "2026-09-27", "status": status}))

    def test_atomic_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            report.save_state(path, {"date": "2026-09-27", "status": "sent"})
            self.assertEqual(report.json.loads(path.read_text())["status"], "sent")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_telegram_failure_does_not_leak_url(self):
        with patch.dict(report.os.environ, TELEGRAM_BOT_TOKEN="secret", TELEGRAM_CHAT_ID="chat"), \
             patch.object(report.urllib.request, "urlopen", side_effect=TimeoutError("secret")):
            self.assertEqual(report.send("test"), "delivery_unknown")


if __name__ == "__main__":
    unittest.main()
