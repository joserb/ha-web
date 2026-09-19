import asyncio
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.notification_rules import DURATIONS, NotificationStore, RuleConflict
from app.notifications import Notifications
from app.telegram import SendResult, TelegramSender


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "alerts.sqlite3")
        self.store = NotificationStore(self.path)
        self.now = 1000.0

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def enable(self, duration="1h", now=1000):
        return self.store.enable("entrada_door", duration, self.store.rule("entrada_door", now)["version"], str(uuid4()), now)

    def observe(self, state, timestamp, retained=False, now=None):
        self.store.observe("entrada_door", "Entrance", state, timestamp, retained, timestamp if now is None else now)

    def queued(self):
        return self.store.db.execute("SELECT count(*) FROM deliveries").fetchone()[0]

    def opening(self):
        self.enable()
        self.observe("closed", 1001)
        self.observe("open", 1002)

    def test_all_durations_and_server_expiry(self):
        for duration, seconds in DURATIONS.items():
            rule = self.enable(duration)
            self.assertEqual(rule["enabled_until"], 1000 + seconds)
        self.assertFalse(self.store.rule("entrada_door", 605800)["active"])

    def test_individual_aggregate_duplicates_and_two_real_openings(self):
        self.opening()
        self.observe("open", 1002)
        self.observe("open", 1003)
        self.assertEqual(self.queued(), 1)
        self.observe("closed", 1004)
        self.observe("open", 1005)
        self.assertEqual(self.queued(), 2)

    def test_unknown_open_and_already_open_on_activation(self):
        self.observe("open", 999)
        self.enable()
        self.observe("open", 1001)
        self.assertEqual(self.queued(), 0)
        self.observe("closed", 1002)
        self.observe("open", 1003)
        self.assertEqual(self.queued(), 1)

    def test_retained_out_of_order_same_timestamp_and_old_events(self):
        self.enable()
        self.observe("closed", 1001, retained=True)
        self.observe("open", 1002, retained=True)
        self.observe("open", 1002)  # aggregate replay
        self.observe("closed", 1001)
        self.observe("closed", 1002)  # conflicting timestamp
        self.observe("open", 1003)
        self.assertEqual(self.queued(), 0)
        self.observe("closed", 1004)
        self.observe("open", 1005, now=1200)
        self.assertEqual(self.queued(), 0)

    def test_future_reading_does_not_poison_baseline(self):
        self.enable()
        self.observe("closed", 1001)
        self.observe("open", 9999, now=1002)
        self.observe("open", 1003)
        self.assertEqual(self.queued(), 1)

    def test_reconnect_does_not_infer_missed_opening(self):
        self.enable()
        self.observe("closed", 1001)
        self.store.reset_baselines()
        self.observe("open", 1002)
        self.assertEqual(self.queued(), 0)
        self.observe("closed", 1003)
        self.observe("open", 1004)
        self.assertEqual(self.queued(), 1)

    def test_rule_and_cursor_survive_restart_without_retroactive_alert(self):
        self.opening()
        self.store.close()
        self.store = NotificationStore(self.path)
        self.assertEqual(self.store.rule("entrada_door", 1005)["enabled_until"], 4600)
        self.observe("open", 1002, retained=True)
        self.observe("open", 1002)
        self.assertEqual(self.queued(), 1)

    def test_disable_cancels_pending_and_is_idempotent(self):
        self.opening()
        result = self.store.disable("entrada_door", 1, 1003)
        self.assertFalse(result["active"])
        self.store.disable("entrada_door", 1, 1004)
        self.assertIsNone(self.store.claim(1004))

    def test_idempotency_and_stale_tab_conflict(self):
        key = str(uuid4())
        first = self.store.enable("entrada_door", "1h", 0, key, 1000)
        repeated = self.store.enable("entrada_door", "1h", 0, key, 1100)
        self.assertEqual(first["enabled_until"], repeated["enabled_until"])
        with self.assertRaises(RuleConflict):
            self.store.enable("entrada_door", "4h", 0, str(uuid4()), 1100)
        self.store.disable("entrada_door", 1, 1101)
        self.assertFalse(self.store.enable("entrada_door", "1h", 0, key, 1102)["active"])
        self.enable(now=1103)
        with self.assertRaises(RuleConflict):
            self.store.disable("entrada_door", 1, 1104)

    def test_expired_or_stale_deliveries_never_send(self):
        self.opening()
        self.assertIsNone(self.store.claim(1200))
        self.observe("closed", 4599)
        self.observe("open", 4600)
        self.assertIsNone(self.store.claim(4600))

    def test_retry_limits_and_restart_during_send(self):
        self.opening()
        delivery = self.store.claim(1003)
        self.store.finish(delivery, "failed", "rate limit", 1003, 10)
        self.assertIsNone(self.store.claim(1010))
        delivery = self.store.claim(1013)
        self.assertEqual(delivery["attempts"], 2)
        self.store.close()
        self.store = NotificationStore(self.path)
        self.assertIsNone(self.store.claim(1014))
        self.assertEqual(self.store.rule("entrada_door", 1014)["last_delivery"]["status"], "delivery_unknown")

    def test_disable_during_rate_limit_response_prevents_retry(self):
        self.opening()
        delivery = self.store.claim(1003)
        self.store.disable("entrada_door", 1, 1004)
        self.store.finish(delivery, "failed", "rate limit", 1005, 10)
        self.assertIsNone(self.store.claim(1015))


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = NotificationStore(":memory:")
        self.sender = TelegramSender("test", "123")
        self.broadcast = AsyncMock()
        self.service = Notifications(self.store, self.sender,
            lambda: SimpleNamespace(sensors=[SimpleNamespace(id="entrada_door", kind="door")]), self.broadcast)
        app = FastAPI()
        app.include_router(self.service.router)
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8080")
        self.headers = {"Origin": "http://localhost:8080"}

    async def asyncTearDown(self):
        await self.client.aclose()
        self.store.close()

    async def put(self, **changes):
        body = dict(duration="1h", version=0, request_id=str(uuid4()))
        body.update(changes)
        return await self.client.put("/api/notification-rules/entrada_door", json=body, headers=self.headers)

    async def test_get_enable_disable_and_broadcast(self):
        self.assertFalse((await self.client.get("/api/notification-rules")).json()["rules"][0]["active"])
        response = await self.put(duration="7d")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["rules"][0]["active"])
        self.broadcast.assert_awaited_once()
        response = await self.client.request("DELETE", "/api/notification-rules/entrada_door", json={"version": 1}, headers=self.headers)
        self.assertFalse(response.json()["rules"][0]["active"])

    async def test_invalid_duration_sensor_and_missing_config(self):
        self.assertEqual((await self.put(duration="15m")).status_code, 422)
        self.assertEqual((await self.put(version=-1)).status_code, 422)
        self.sender.token = ""
        self.assertEqual((await self.put()).status_code, 503)
        self.assertEqual((await self.client.put("/api/notification-rules/bano_temp", json=dict(duration="1h", version=0, request_id=str(uuid4())), headers=self.headers)).status_code, 404)

    async def test_origin_host_and_cross_site_protection(self):
        for origin in ["http://evil.example", "null", "http://127.0.0.1:8080", ""]:
            self.headers = {"Origin": origin}
            self.assertEqual((await self.put()).status_code, 403)
        self.headers = {"Origin": "http://localhost:8080", "Sec-Fetch-Site": "cross-site"}
        self.assertEqual((await self.put()).status_code, 403)

    async def test_conflict_refresh_and_no_secrets(self):
        self.assertEqual((await self.put()).status_code, 200)
        self.assertEqual((await self.put()).status_code, 409)
        body = (await self.client.get("/api/notification-rules")).text
        self.assertNotIn('"token"', body)
        self.assertNotIn('"chat_id"', body)


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.sender = TelegramSender("secret-token", "123")
        self.delivery = dict(label="Entrance", timestamp=1000)

    @patch("urllib.request.urlopen")
    def test_success(self, urlopen):
        urlopen.return_value.__enter__.return_value = io.BytesIO(b'{"ok":true}')
        self.assertEqual(self.sender._send(self.delivery).status, "sent")
        payload = json.loads(urlopen.call_args.args[0].data)
        self.assertIn("puerta abierta", payload["text"])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 8)

    @patch("urllib.request.urlopen")
    def test_429_permanent_and_ambiguous_failures(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("hidden", 429, "limit", {}, io.BytesIO(b'{"parameters":{"retry_after":15}}'))
        self.assertEqual(self.sender._send(self.delivery).retry_after, 15)
        urlopen.side_effect = urllib.error.HTTPError("hidden", 403, "forbidden", {}, io.BytesIO(b'{}'))
        self.assertIsNone(self.sender._send(self.delivery).retry_after)
        urlopen.side_effect = TimeoutError("secret-token")
        result = self.sender._send(self.delivery)
        self.assertEqual(result.status, "delivery_unknown")
        self.assertNotIn("secret-token", result.detail)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_sender_wait_does_not_block_rule_changes(self):
        store = NotificationStore(":memory:")
        clock = 1000
        store.enable("entrada_door", "1h", 0, str(uuid4()), clock)
        store.observe("entrada_door", "Entrance", "closed", 1001, False, 1001)
        store.observe("entrada_door", "Entrance", "open", 1002, False, 1002)
        entered, release = asyncio.Event(), asyncio.Event()

        async def send(_):
            entered.set()
            await release.wait()
            return SendResult("sent")

        sender = SimpleNamespace(configured=True, send=send)
        service = Notifications(store, sender, lambda: SimpleNamespace(sensors=[]), AsyncMock())
        with patch("app.notifications.time.time", return_value=1003):
            task = asyncio.create_task(service.run())
            try:
                await asyncio.wait_for(entered.wait(), 1)
                self.assertTrue((await service.get_rules())["rules"][0]["active"])
                store.disable("entrada_door", 1, 1004)
                self.assertFalse(store.rule("entrada_door", 1004)["active"])
                release.set()
                await asyncio.sleep(0)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                store.close()
