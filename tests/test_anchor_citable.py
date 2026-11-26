"""The packet must not publish an anchor the premise check would refuse.

knowledge.check refuses a premise whose source kind is outside
CITABLE_KINDS, so an anchor on such a source is a citation the reviewer can
select and never use. r54/r55 measured what that costs: a reviewer who follows
the packet exactly gets a review_failure, burns the request, and the target
drops out of the default queue by packet digest.

`falsifier_hit` was the known case (test_falsifier_bridge). `question_evidence`
was not: three live packets in the real domain published one, and all three sat
at the head of the review queue.
"""
import unittest

import dojo.anchors as anchors
from dojo.anchors import CITABLE_KINDS

class _StubKnowledge:
    """Only what anchor_catalog reads: exact source text by event."""

    TEXTS = {1: 'organization note', 2: 'a real quote'}

    def source(self, event):
        return {'event': event, 'text': self.TEXTS[event]}

    def observed_tool_text(self, event):
        return self.TEXTS[event]


def _source(event, kind):
    return {'event': event, 'kind': kind, 'text': _StubKnowledge.TEXTS[event],
            'dependency_status': {'state': 'current_interpretation'}}


class AnchorCitableTests(unittest.TestCase):
    def test_the_catalog_withholds_an_uncitable_kind_but_still_shows_the_source(self):
        """Withholding the anchor must not hide the material.

        review_context.causes reads these events, so the source stays in the
        packet even though it can never be cited.
        """
        sources = [_source(1, 'question_evidence'), _source(2, 'user')]
        catalog = anchors.anchor_catalog(_StubKnowledge(), sources)
        self.assertEqual([2], [a['source_event'] for a in catalog])
        # The withheld event is still handed to the catalog: it is filtered
        # from the anchors, not from the packet's sources.
        self.assertEqual([1, 2], [s['event'] for s in sources])

    def test_a_hit_is_still_withheld_like_before(self):
        """The r20 rule must not regress while widening to other kinds."""
        sources = [_source(1, 'falsifier_hit'), _source(2, 'user')]
        catalog = anchors.anchor_catalog(_StubKnowledge(), sources)
        self.assertEqual([2], [a['source_event'] for a in catalog])

    def test_the_check_and_the_catalog_share_one_definition(self):
        """A kind may not be citable in the catalog and refused by check."""
        self.assertEqual({'user', 'tool_result', 'knowledge_proposal', 'reflection'},
                         set(CITABLE_KINDS))
        self.assertNotIn('question_evidence', CITABLE_KINDS)
        self.assertNotIn('falsifier_hit', CITABLE_KINDS)

if __name__ == '__main__':
    unittest.main()
