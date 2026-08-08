import unittest

from app.link_state import (
    BRIDGE_STATE_TOPIC,
    PI_AVAILABILITY_TOPIC,
    LinkState,
    parse_bridge_state,
    parse_pi_availability,
)


class LinkParsingTests(unittest.TestCase):
    def test_only_documented_bridge_payloads_are_accepted(self):
        self.assertIs(parse_bridge_state("1"), True)
        self.assertIs(parse_bridge_state(" 0\n"), False)
        for invalid in ["", "up", "true", "2", "01"]:
            self.assertIsNone(parse_bridge_state(invalid), invalid)

    def test_only_documented_availability_payloads_are_accepted(self):
        self.assertEqual(parse_pi_availability("ONLINE"), "online")
        self.assertEqual(parse_pi_availability(" offline "), "offline")
        for invalid in ["", "up", "1", "unknown"]:
            self.assertIsNone(parse_pi_availability(invalid), invalid)


class LinkStateTests(unittest.TestCase):
    def setUp(self):
        self.state = LinkState()

    def test_starts_unknown(self):
        self.assertEqual(
            self.state.snapshot(),
            {"bridge_connected": None, "pi_availability": None},
        )

    def test_transitions_are_reported_once(self):
        self.assertTrue(self.state.apply(BRIDGE_STATE_TOPIC, "1"))
        self.assertFalse(self.state.apply(BRIDGE_STATE_TOPIC, "1"))
        self.assertTrue(self.state.apply(BRIDGE_STATE_TOPIC, "0"))
        self.assertIs(self.state.bridge_connected, False)

    def test_invalid_payload_keeps_the_previous_value(self):
        self.state.apply(PI_AVAILABILITY_TOPIC, "online")
        self.assertFalse(self.state.apply(PI_AVAILABILITY_TOPIC, "maybe"))
        self.assertEqual(self.state.pi_availability, "online")

    def test_unrelated_topics_are_not_handled(self):
        self.assertFalse(self.state.handles("home/salon/temp"))
        self.assertFalse(self.state.apply("home/salon/temp", "1"))

    def test_reset_forgets_both_links(self):
        self.state.apply(BRIDGE_STATE_TOPIC, "1")
        self.state.apply(PI_AVAILABILITY_TOPIC, "online")
        self.assertTrue(self.state.reset())
        self.assertEqual(
            self.state.snapshot(),
            {"bridge_connected": None, "pi_availability": None},
        )
        self.assertFalse(self.state.reset())


if __name__ == "__main__":
    unittest.main()
