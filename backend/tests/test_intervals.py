import unittest
from datetime import datetime, timezone

from app.intervals import build_intervals


class IntervalTests(unittest.TestCase):
    def test_pairs_and_collapses_states(self):
        events = [
            {"time": datetime(2026, 1, 1, 10, tzinfo=timezone.utc), "value": "open"},
            {"time": datetime(2026, 1, 1, 10, 1, tzinfo=timezone.utc), "value": "open"},
            {"time": datetime(2026, 1, 1, 10, 5, tzinfo=timezone.utc), "value": "closed"},
        ]
        result = build_intervals(events, {"open"}, datetime(2026, 1, 1, 11, tzinfo=timezone.utc))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["end"], events[2]["time"])

    def test_open_interval_continues_to_now(self):
        now = datetime(2026, 1, 1, 11, tzinfo=timezone.utc)
        result = build_intervals([{"time": datetime(2026, 1, 1, 10, tzinfo=timezone.utc), "value": "active"}], {"active"}, now)
        self.assertTrue(result[0]["active"])
        self.assertEqual(result[0]["end"], now)
