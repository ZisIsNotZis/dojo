"""Regression guards for the notice-failure identifiability probe.

These assert only properties of the declared deterministic channels over the
16 declared mechanism subsets. They certify no measurement, no real occurrence
rate and no reader behavior - see the probe's scope note.
"""
import importlib.util
import itertools
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    'notice_probe', Path(__file__).resolve().parents[1] / 'scripts/probe_notice_identifiability.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

ALL_PAIRS = {tuple(sorted(p)) for p in itertools.combinations(probe.MECHANISMS, 2)}


class NoticeIdentifiabilityTests(unittest.TestCase):
    def test_two_cheapest_channels_separate_every_singleton_pair(self):
        # 'r+s' is the whole battery's cheapest claim; it must not silently need 'd' or 't'.
        self.assertGreaterEqual(probe.pairwise_separated(probe.partition(('r', 's'))), ALL_PAIRS)
        for k in (1,):
            for combo in itertools.combinations(('d', 't', 'r', 's', 'c'), k):
                self.assertLess(probe.pairwise_separated(probe.partition(combo)), ALL_PAIRS)

    def test_no_failure_subset_is_always_the_first_endpoint_of_a_collapsed_pair(self):
        # The fix-4 bug stored (('inconspicuous',), ()) and hid the no-failure end.
        pairs = probe.undistinguished_pairs(probe.partition(('d',)))
        self.assertIn(((), ('inconspicuous',)), [tuple(tuple(u) for u in p) for p in pairs])
        for a, b in pairs:
            if a == () or b == ():
                self.assertEqual((), a)

    def test_attention_channel_separates_unnoticed_from_no_failure_but_delivery_does_not(self):
        self.assertNotIn(((), ('inconspicuous',)),
                         [tuple(tuple(u) for u in p) for p in probe.undistinguished_pairs(probe.partition(('t',)))])
        self.assertIn(((), ('inconspicuous',)),
                      [tuple(tuple(u) for u in p) for p in probe.undistinguished_pairs(probe.partition(('d',)))])

    def test_no_declared_scheme_certifies_several_mechanisms_at_once(self):
        for name, scheme in probe.SCHEMES:
            with self.subTest(scheme=name):
                self.assertEqual([], probe.report(scheme)['multi_mechanism_subsets_identified'])

    def test_independent_counting_agrees_for_every_declared_scheme(self):
        for name, scheme in probe.SCHEMES:
            with self.subTest(scheme=name):
                rep = probe.report(scheme)
                self.assertEqual((rep['classes'], rep['largest_class']),
                                 probe.independently_counted(scheme))


if __name__ == '__main__':
    unittest.main()
