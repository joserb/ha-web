import unittest

from app.publish_policy import is_allowed, load_allowlist


class PublishPolicyTests(unittest.TestCase):
    def test_default_allowlist_is_empty(self):
        for raw in [None, "", "   ", ",,"]:
            self.assertEqual(load_allowlist(raw), frozenset(), repr(raw))

    def test_nothing_is_publishable_without_configuration(self):
        empty = load_allowlist(None)
        self.assertFalse(is_allowed("home/salon/light/set", empty))
        self.assertFalse(is_allowed("/ZRO/commands", empty))

    def test_listed_topics_are_publishable(self):
        allowlist = load_allowlist(" home/salon/light/set , /ZRO/commands ")
        self.assertEqual(allowlist, {"home/salon/light/set", "/ZRO/commands"})
        self.assertTrue(is_allowed("home/salon/light/set", allowlist))
        self.assertFalse(is_allowed("home/salon/light", allowlist))

    def test_wildcards_are_rejected_in_the_allowlist(self):
        self.assertEqual(load_allowlist("home/#,home/+/set,$SYS/x"), frozenset())

    def test_wildcards_are_rejected_when_publishing(self):
        allowlist = load_allowlist("home/salon/light/set")
        self.assertFalse(is_allowed("home/#", allowlist))
        self.assertFalse(is_allowed("", allowlist))
        self.assertFalse(is_allowed("x" * 200, allowlist))


if __name__ == "__main__":
    unittest.main()
