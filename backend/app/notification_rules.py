"""Persistent temporary rules and outbox. Owned by the single asyncio worker."""
import json
import sqlite3
from pathlib import Path

DURATIONS = {"1h": 3600, "4h": 14400, "8h": 28800, "1d": 86400, "7d": 604800}
MAX_EVENT_AGE = 120


class RuleConflict(Exception):
    pass


class NotificationStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS rules (
                sensor_id TEXT PRIMARY KEY, enabled_from REAL NOT NULL,
                enabled_until REAL NOT NULL, version INTEGER NOT NULL,
                duration TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS readings (
                sensor_id TEXT PRIMARY KEY, timestamp REAL NOT NULL, state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                id INTEGER PRIMARY KEY, sensor_id TEXT NOT NULL, timestamp REAL NOT NULL,
                label TEXT NOT NULL, version INTEGER NOT NULL, status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL,
                detail TEXT, UNIQUE(sensor_id, timestamp)
            );
        """)
        # A process may have died after Telegram accepted a request. Never replay it.
        with self.db:
            self.db.execute("UPDATE deliveries SET status='delivery_unknown', detail='Delivery interrupted; not retried' WHERE status='sending'")
        self.baselined: set[str] = set()

    def close(self):
        self.db.close()

    def reset_baselines(self):
        self.baselined.clear()

    def rule(self, sensor_id: str, now: float) -> dict:
        row = self.db.execute("SELECT * FROM rules WHERE sensor_id=?", (sensor_id,)).fetchone()
        result = dict(row) if row else dict(sensor_id=sensor_id, enabled_from=0, enabled_until=0, version=0, duration="1h")
        result["active"] = result["enabled_until"] > now
        last = self.db.execute("SELECT timestamp, status, detail FROM deliveries WHERE sensor_id=? ORDER BY id DESC LIMIT 1", (sensor_id,)).fetchone()
        result["last_delivery"] = dict(last) if last else None
        return result

    def rules(self, now: float) -> list[dict]:
        return [self.rule(row[0], now) for row in self.db.execute("SELECT sensor_id FROM rules ORDER BY sensor_id")]

    def enable(self, sensor_id: str, duration: str, expected_version: int, request_id: str, now: float) -> dict:
        seconds = DURATIONS[duration]
        fingerprint = json.dumps([sensor_id, duration, expected_version])
        with self.db:
            prior = self.db.execute("SELECT fingerprint FROM requests WHERE request_id=?", (request_id,)).fetchone()
            if prior:
                if prior[0] != fingerprint:
                    raise RuleConflict("Request ID already used")
                return self.rule(sensor_id, now)
            current = self.rule(sensor_id, now)
            if current["version"] != expected_version:
                raise RuleConflict("Rule changed in another tab; refreshed")
            start = current["enabled_from"] if current["active"] else now
            # Extend to at least the selected duration from now, never shorten.
            end = max(current["enabled_until"], now + seconds)
            self.db.execute("INSERT OR REPLACE INTO rules VALUES (?, ?, ?, ?, ?)",
                            (sensor_id, start, end, expected_version + 1, duration))
            self.db.execute("INSERT INTO requests VALUES (?, ?)", (request_id, fingerprint))
            self.db.execute("UPDATE deliveries SET status='cancelled', detail='Rule replaced' WHERE sensor_id=? AND status='pending'", (sensor_id,))
        return self.rule(sensor_id, now)

    def disable(self, sensor_id: str, expected_version: int, now: float) -> dict:
        with self.db:
            current = self.rule(sensor_id, now)
            if not current["active"]:
                return current
            if current["version"] != expected_version:
                raise RuleConflict("Rule changed in another tab; refreshed")
            self.db.execute("UPDATE rules SET enabled_until=?, version=version+1 WHERE sensor_id=?", (now, sensor_id))
            self.db.execute("UPDATE deliveries SET status='cancelled', detail='Alerts disabled' WHERE sensor_id=? AND status='pending'", (sensor_id,))
        return self.rule(sensor_id, now)

    def observe(self, sensor_id: str, label: str, state: str, timestamp: float, retained: bool, now: float):
        if state not in {"open", "closed"} or timestamp > now + 5:
            return
        with self.db:
            old = self.db.execute("SELECT * FROM readings WHERE sensor_id=?", (sensor_id,)).fetchone()
            if old and timestamp < old["timestamp"]:
                return
            if old and timestamp == old["timestamp"]:
                if state == old["state"]:
                    self.baselined.add(sensor_id)
                return
            ready = sensor_id in self.baselined
            self.baselined.add(sensor_id)
            self.db.execute("INSERT OR REPLACE INTO readings VALUES (?, ?, ?)", (sensor_id, timestamp, state))
            rule = self.rule(sensor_id, now)
            if (ready and old and old["state"] == "closed" and state == "open"
                    and not retained and rule["active"]
                    and rule["enabled_from"] < timestamp <= now
                    and now - timestamp <= MAX_EVENT_AGE):
                self.db.execute("INSERT OR IGNORE INTO deliveries (sensor_id, timestamp, label, version, status, next_attempt) VALUES (?, ?, ?, ?, 'pending', ?)",
                                (sensor_id, timestamp, label, rule["version"], now))

    def claim(self, now: float) -> dict | None:
        with self.db:
            self.db.execute("""UPDATE deliveries SET status='cancelled', detail='Expired or rule inactive'
                WHERE status='pending' AND (timestamp < ? OR NOT EXISTS (
                    SELECT 1 FROM rules r WHERE r.sensor_id=deliveries.sensor_id
                    AND r.version=deliveries.version AND r.enabled_until > ?))""", (now - MAX_EVENT_AGE, now))
            row = self.db.execute("SELECT * FROM deliveries WHERE status='pending' AND next_attempt <= ? ORDER BY id LIMIT 1", (now,)).fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE deliveries SET status='sending', attempts=attempts+1 WHERE id=?", (row["id"],))
            result = dict(row)
            result["attempts"] += 1
            return result

    def finish(self, delivery: dict, status: str, detail: str | None, now: float, retry_after: float | None = None):
        with self.db:
            if retry_after is not None:
                rule = self.rule(delivery["sensor_id"], now)
                retry_at = now + max(1, retry_after)
                if (delivery["attempts"] < 3 and rule["active"] and rule["version"] == delivery["version"]
                        and retry_at < min(rule["enabled_until"], delivery["timestamp"] + MAX_EVENT_AGE)):
                    status = "pending"
                    self.db.execute("UPDATE deliveries SET next_attempt=? WHERE id=?", (retry_at, delivery["id"]))
            self.db.execute("UPDATE deliveries SET status=?, detail=? WHERE id=?", (status, detail, delivery["id"]))
