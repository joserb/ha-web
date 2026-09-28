import json
import unittest

from app.door import DoorWatcher, door_reading


def message(state, updated_at="2026-09-28T10:00:00Z", **extra):
    return json.dumps({"type": "contact", "state": state, "updated_at": updated_at, **extra})


class DoorReadingTests(unittest.TestCase):
    def test_individual_and_aggregate_topics(self):
        single = door_reading("/ZRO/env/entrada", message("OPEN"), "entrada")
        aggregate = door_reading("/ZRO/env/state", json.dumps({"devices": {"entrada": json.loads(message("open"))}}),
                                 "entrada")
        self.assertEqual(single, aggregate)
        self.assertEqual(single[0], "open")

    def test_other_devices_and_garbage_are_ignored(self):
        self.assertIsNone(door_reading("/ZRO/env/salon", message("open"), "entrada"))
        self.assertIsNone(door_reading("/ZRO/env/entrada", "not json", "entrada"))
        self.assertIsNone(door_reading("/ZRO/env/entrada", json.dumps({"type": "climate"}), "entrada"))
        self.assertIsNone(door_reading("/ZRO/env/entrada", message("open", updated_at="yesterday"), "entrada"))


class DoorWatcherTests(unittest.TestCase):
    def setUp(self):
        self.watcher = DoorWatcher()

    def test_first_reading_only_sets_the_baseline(self):
        self.assertIsNone(self.watcher.observe("open", 100, False, 100))
        self.assertEqual(self.watcher.observe("closed", 101, False, 101), "closed")
        self.assertEqual(self.watcher.observe("open", 102, False, 102), "open")

    def test_duplicates_from_both_topics_count_once(self):
        self.watcher.observe("closed", 100, False, 100)
        self.assertEqual(self.watcher.observe("open", 101, False, 101), "open")
        self.assertIsNone(self.watcher.observe("open", 101, False, 101))
        self.assertIsNone(self.watcher.observe("open", 102, False, 102))

    def test_retained_old_and_out_of_order_readings_never_trigger(self):
        self.watcher.observe("closed", 100, False, 100)
        self.assertIsNone(self.watcher.observe("open", 101, True, 101))
        self.assertIsNone(self.watcher.observe("closed", 50, False, 102))
        self.assertIsNone(self.watcher.observe("closed", 110, False, 110 + 121))

    def test_reconnect_needs_a_new_baseline(self):
        self.watcher.observe("closed", 100, False, 100)
        self.watcher.reset()
        # El broker reproduce el retenido conocido: confirma la línea base.
        self.assertIsNone(self.watcher.observe("closed", 100, True, 200))
        self.assertEqual(self.watcher.observe("open", 201, False, 201), "open")

    def test_future_timestamps_are_rejected(self):
        self.watcher.observe("closed", 100, False, 100)
        self.assertIsNone(self.watcher.observe("open", 200, False, 101))


if __name__ == "__main__":
    unittest.main()
