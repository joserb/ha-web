import json
import unittest
from datetime import datetime, timezone

from app.current_state import CurrentState, build_recovered_states, supersedes


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


class SupersedesTests(unittest.TestCase):
    """Una lectura vieja no puede desbancar a una nueva."""

    def state(self, when: datetime) -> CurrentState:
        return CurrentState(payload="closed", updated_at=when, source="zro-pi")

    def test_first_reading_is_always_accepted(self):
        self.assertTrue(supersedes(None, datetime(2026, 9, 18, 16, 43, tzinfo=timezone.utc)))

    def test_newer_reading_replaces_the_current_state(self):
        previous = self.state(datetime(2026, 9, 18, 16, 43, tzinfo=timezone.utc))
        self.assertTrue(supersedes(previous, datetime(2026, 9, 20, 4, 45, tzinfo=timezone.utc)))

    def test_retained_replay_does_not_move_the_state_backwards(self):
        # El caso real: al reconectar, el broker reprodujo un retenido del 18
        # y pisó la lectura del 20 recuperada desde InfluxDB.
        recovered = CurrentState(payload="closed", updated_at=datetime(2026, 9, 20, 4, 45, tzinfo=timezone.utc), source="influxdb")
        self.assertFalse(supersedes(recovered, datetime(2026, 9, 18, 16, 43, tzinfo=timezone.utc)))

    def test_same_timestamp_is_not_a_new_reading(self):
        when = datetime(2026, 9, 20, 4, 45, tzinfo=timezone.utc)
        self.assertFalse(supersedes(self.state(when), when))
