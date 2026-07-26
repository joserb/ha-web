import json
import unittest
from datetime import datetime, timezone

from app.current_state import build_recovered_states


class CurrentStateTests(unittest.TestCase):
    def test_simple_value_is_recovered_as_plain_payload(self):
        now = datetime.now(timezone.utc)
        states = build_recovered_states([{
            "location": "home/salon",
            "measurement": "temp",
            "field": "value",
            "value": 22.5,
            "time": now,
        }])
        self.assertEqual(states["home/salon/temp"].payload, "22.5")
        self.assertEqual(states["home/salon/temp"].source, "influxdb")

    def test_multiple_fields_are_recovered_as_json(self):
        now = datetime.now(timezone.utc)
        rows = [
            {
                "location": "home/salon",
                "measurement": "climate",
                "field": "temperature",
                "value": 22.5,
                "time": now,
            },
            {
                "location": "home/salon",
                "measurement": "climate",
                "field": "humidity",
                "value": 48.0,
                "time": now,
            },
        ]
        payload = build_recovered_states(rows)["home/salon/climate"].payload
        self.assertEqual(json.loads(payload), {"temperature": 22.5, "humidity": 48.0})


if __name__ == "__main__":
    unittest.main()
