"""Guards for the adversarial collision probe.

These lock the NEGATIVE result: under alternate information routes, `r+s`
merges two pairs it separated over declared subsets. They also lock the
t-semantics hole, so a future change cannot silently make 't separates' look
like real attention detection.
"""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    'collision_probe', Path(__file__).resolve().parents[1] / 'scripts/probe_notice_collisions.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

SCHEME = ('r', 's')
COLLEAGUE_PAIR = (('colleague', 'bypass'), ('declared', 'unread'))
TIMELY_PAIR = (('timely', 'late'), ('declared',))


class NoticeCollisionTests(unittest.TestCase):
    def setUp(self):
        self.space = probe.build_space()

    def _sig(self, label):
        return probe.signature(probe.find(self.space, label), SCHEME)

    def test_colleague_route_collides_with_unread_under_r_plus_s(self):
        self.assertEqual(self._sig(COLLEAGUE_PAIR[0]), self._sig(COLLEAGUE_PAIR[1]))

    def test_timely_value_collides_with_no_failure_under_r_plus_s(self):
        self.assertEqual(self._sig(TIMELY_PAIR[0]), self._sig(TIMELY_PAIR[1]))

    def test_declared_subsets_still_separate_every_singleton_pair(self):
        # The wide claim must remain true where it was claimed: singletons only.
        for i in range(len(probe.MECHANISMS)):
            for j in range(i + 1, len(probe.MECHANISMS)):
                a = ('declared', probe.MECHANISMS[i])
                b = ('declared', probe.MECHANISMS[j])
                self.assertNotEqual(self._sig(a), self._sig(b))

    def test_attention_channel_fires_without_any_notice_opened(self):
        # The hole: t is True while r is False for a bypassing colleague route.
        tr = probe.find(self.space, COLLEAGUE_PAIR[0])
        self.assertTrue(probe.value(tr, 't'))
        self.assertFalse(probe.value(tr, 'r'))

    def test_cheapest_breakers_are_the_recorded_ones(self):
        self.assertEqual(['t', 'c', 'who'],
                         probe.cheapest_breakers(self.space, SCHEME, *COLLEAGUE_PAIR))
        self.assertEqual(['d', 't', 'ts'],
                         probe.cheapest_breakers(self.space, SCHEME, *TIMELY_PAIR))


if __name__ == '__main__':
    unittest.main()
