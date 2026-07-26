import unittest

from app.catalog import SensorCatalog, load_catalog


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


if __name__ == "__main__":
    unittest.main()
