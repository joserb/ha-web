import unittest

from app.time_ranges import TimeRange, get_legacy_hours_spec, get_time_range_spec


class TimeRangeTests(unittest.TestCase):
    def test_every_public_range_has_a_flux_spec(self):
        public_values = [
            "1h", "6h", "12h", "1d", "7d",
            "30d", "3m", "6m", "1y", "forever",
        ]
        self.assertEqual(set(TimeRange), set(map(TimeRange, public_values)))
        for period in TimeRange:
            spec = get_time_range_spec(period)
            self.assertTrue(spec.start)
            self.assertTrue(spec.window)

    def test_forever_uses_the_beginning_of_retained_data(self):
        self.assertEqual(get_time_range_spec(TimeRange.FOREVER).start, "0")

    def test_legacy_hours_remains_bounded(self):
        with self.assertRaises(ValueError):
            get_legacy_hours_spec(0)
        with self.assertRaises(ValueError):
            get_legacy_hours_spec(8761)

    def test_legacy_window_grows_with_the_period(self):
        self.assertEqual(get_legacy_hours_spec(1).window, "1m")
        self.assertEqual(get_legacy_hours_spec(24).window, "15m")
        self.assertEqual(get_legacy_hours_spec(168).window, "1h")


if __name__ == "__main__":
    unittest.main()
