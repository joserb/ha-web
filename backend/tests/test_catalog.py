import os
import unittest
from unittest import mock

from app.catalog import (
    DEFAULT_EVENT_STALE_AFTER_SECONDS,
    DEFAULT_STALE_AFTER_SECONDS,
    SensorCatalog,
    build_zro_catalog,
    event_stale_after_seconds,
    load_catalog,
    stale_after_seconds,
)


class SensorCatalogTests(unittest.TestCase):
    def test_packaged_catalog_is_valid(self):
        catalog = load_catalog()
        self.assertEqual(len(catalog.sensors), 6)
        self.assertEqual(
            {sensor.card for sensor in catalog.sensors},
            {"meter", "timeline"},
        )
        self.assertIn("humidities", {sensor.family for sensor in catalog.sensors})

    def test_duplicate_topics_are_rejected(self):
        sensor = load_catalog().sensors[0].model_dump()
        duplicate = {**sensor, "id": "another_sensor"}
        with self.assertRaises(ValueError):
            SensorCatalog.model_validate({"sensors": [sensor, duplicate]})

    def test_topic_must_match_location_and_measurement(self):
        sensor = load_catalog().sensors[0].model_dump()
        sensor["topic"] = "home/another/temp"
        with self.assertRaises(ValueError):
            SensorCatalog.model_validate({"sensors": [sensor]})


class StaleLimitTests(unittest.TestCase):
    def test_default_is_one_hour_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(stale_after_seconds(), DEFAULT_STALE_AFTER_SECONDS)

    def test_environment_overrides_the_default(self):
        with mock.patch.dict("os.environ", {"SENSOR_STALE_AFTER_SECONDS": "900"}):
            self.assertEqual(stale_after_seconds(), 900)

    def test_invalid_values_fall_back_to_the_default(self):
        for raw in ["0", "-1", "cuatro", "99999999999"]:
            with mock.patch.dict("os.environ", {"SENSOR_STALE_AFTER_SECONDS": raw}):
                self.assertEqual(stale_after_seconds(), DEFAULT_STALE_AFTER_SECONDS, raw)

    def test_generated_catalog_uses_the_configured_limit(self):
        device = {"type": "climate", "temperature": 21.0}
        with mock.patch.dict("os.environ", {"SENSOR_STALE_AFTER_SECONDS": "1800"}):
            catalog = build_zro_catalog({"salon": device})
        self.assertEqual({sensor.stale_after_seconds for sensor in catalog.sensors}, {1800})


class EventStaleLimitTests(unittest.TestCase):
    """Puerta y vibración callan cuando no pasa nada; su silencio no es avería."""

    def test_default_is_a_day_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(event_stale_after_seconds(), DEFAULT_EVENT_STALE_AFTER_SECONDS)

    def test_environment_overrides_the_default(self):
        with mock.patch.dict("os.environ", {"EVENT_SENSOR_STALE_AFTER_SECONDS": "43200"}):
            self.assertEqual(event_stale_after_seconds(), 43200)

    def test_invalid_values_fall_back_to_the_default(self):
        for raw in ["0", "-1", "cuatro", "99999999999"]:
            with mock.patch.dict("os.environ", {"EVENT_SENSOR_STALE_AFTER_SECONDS": raw}):
                self.assertEqual(event_stale_after_seconds(), DEFAULT_EVENT_STALE_AFTER_SECONDS, raw)

    def test_event_sensors_do_not_use_the_periodic_limit(self):
        devices = {
            "entrada": {"type": "contact", "contact": True, "battery": 88},
            "comedero-gatos": {"type": "vibration", "vibration": False},
            "salon": {"type": "climate", "temperature": 21.0},
        }
        with mock.patch.dict(os.environ, {}, clear=True):
            catalog = build_zro_catalog(devices)
        by_kind = {sensor.kind: sensor.stale_after_seconds for sensor in catalog.sensors}
        self.assertEqual(by_kind["door"], DEFAULT_EVENT_STALE_AFTER_SECONDS)
        self.assertEqual(by_kind["vibration"], DEFAULT_EVENT_STALE_AFTER_SECONDS)
        self.assertEqual(by_kind["temperature"], DEFAULT_STALE_AFTER_SECONDS)

    def test_battery_follows_its_own_device(self):
        """Viaja en los mismos mensajes que el sensor, así que hereda su ritmo."""
        devices = {
            "entrada": {"type": "contact", "contact": True, "battery": 88},
            "salon": {"type": "climate", "temperature": 21.0, "battery": 74},
        }
        with mock.patch.dict(os.environ, {}, clear=True):
            catalog = build_zro_catalog(devices)
        by_id = {sensor.id: sensor.stale_after_seconds for sensor in catalog.sensors}
        self.assertEqual(by_id["entrada_battery"], DEFAULT_EVENT_STALE_AFTER_SECONDS)
        self.assertEqual(by_id["salon_battery"], DEFAULT_STALE_AFTER_SECONDS)

    def test_each_limit_is_configured_separately(self):
        devices = {"entrada": {"type": "contact", "contact": False}, "salon": {"type": "climate", "temperature": 21.0}}
        env = {"SENSOR_STALE_AFTER_SECONDS": "600", "EVENT_SENSOR_STALE_AFTER_SECONDS": "7200"}
        with mock.patch.dict("os.environ", env):
            catalog = build_zro_catalog(devices)
        by_kind = {sensor.kind: sensor.stale_after_seconds for sensor in catalog.sensors}
        self.assertEqual(by_kind["door"], 7200)
        self.assertEqual(by_kind["temperature"], 600)

    def test_a_quiet_house_does_not_turn_the_door_card_red(self):
        """Caso real: puerta y su batería a 1,9 h sin reportar, sin avería."""
        devices = {"entrada": {"type": "contact", "contact": False, "battery": 88}}
        with mock.patch.dict(os.environ, {}, clear=True):
            catalog = build_zro_catalog(devices)
        age = 1.9 * 3600
        self.assertTrue(all(age < sensor.stale_after_seconds for sensor in catalog.sensors))


if __name__ == "__main__":
    unittest.main()
