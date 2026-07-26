import json
import unittest

from app.catalog import build_zro_catalog
from app.zro_env import decode_env_message, normalize_device


class ZroEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.climate = {
            "type": "climate",
            "temperature": 23.71,
            "humidity": 64.19,
            "pressure": 994.2,
            "battery": 83,
            "updated_at": "2026-07-26T18:55:50.245612+00:00",
        }

    def test_climate_payload_preserves_historical_topic_names(self):
        readings = {item.topic: item.payload for item in normalize_device("terraza", self.climate)}
        self.assertEqual(readings["home/terraza/temp"], "23.71")
        self.assertEqual(readings["home/terraza/humidity"], "64.19")
        self.assertEqual(readings["home/terraza/battery"], "83")

    def test_contact_state_becomes_door_reading(self):
        readings = normalize_device("entrada", {
            "type": "contact",
            "state": "CLOSED",
            "updated_at": "2026-07-26T18:50:07+00:00",
        })
        self.assertEqual(readings[0].topic, "home/entrada/door")
        self.assertEqual(readings[0].payload, "closed")

    def test_aggregate_is_decoded_as_inventory(self):
        payload = json.dumps({"devices": {"terraza": self.climate}})
        self.assertIn("terraza", decode_env_message("/ZRO/env/state", payload))

    def test_catalog_is_generated_from_available_fields(self):
        catalog = build_zro_catalog({"terraza": self.climate})
        self.assertEqual(
            {sensor.measurement for sensor in catalog.sensors},
            {"temp", "humidity", "pressure", "battery"},
        )


if __name__ == "__main__":
    unittest.main()
