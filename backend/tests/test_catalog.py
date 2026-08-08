import os
import unittest
from unittest import mock

from app.catalog import (
    DEFAULT_STALE_AFTER_SECONDS,
    SensorCatalog,
    build_zro_catalog,
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


if __name__ == "__main__":
    unittest.main()
