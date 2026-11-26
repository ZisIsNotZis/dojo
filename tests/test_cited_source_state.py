"""r93: a relation's screen line must say whether the quotation it rests on was
replaced, and must not fold 'cannot read it' into 'still valid'.

The failure this pins down was observed on the repo's own files: 25 live
relations quote an event that a later revision replaced, and the screen printed
nothing about it -- `annotation_history` tracks whether the *relation* moved,
never the source it quotes.

Identity note: these fixtures are `synthetic=True`. They pin the four sentences
and the model-input boundary; they are NOT the observed-on-real-files claim,
which is reported separately with the CLI output it came from.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dojo.inquiry import Inquiry
from dojo.questions import cited_source_state

PROPOSAL = {'statement': 'A claim', 'kind': 'causal', 'method': 'hypothesis',
            'premises': [], 'assumptions': ['a'], 'conditions': ['c'],
            'alternatives': ['b'], 'falsifier': 'f', 'revises': None}


class CitedSourceStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = Inquiry(Path(self.tmp.name) / 'db',
                         SimpleNamespace(config=SimpleNamespace(model='deepseek-flash', api_key=None)),
                         synthetic=True)

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def test_replaced_source_says_so_and_names_the_replacement(self):
        old = self.q.record('tool_result', {'status': 'executed', 'result': {'note': 'first'}})
        new = self.q.record('tool_result', {'status': 'executed', 'result': {'note': 'second'}})
        self.q.dependencies.revise(old, new, 'a later reading replaced it')
        line = cited_source_state(self.q.knowledge, old)
        self.assertIn('后来已被换掉', line)
        self.assertIn(str(new), line)
        # It reports the ledger, not a verdict on the proposition.
        self.assertNotIn('这条命题是错的', line)

    def test_live_source_is_not_described_as_support(self):
        live = self.q.record('tool_result', {'status': 'executed', 'result': {'note': 'live'}})
        line = cited_source_state(self.q.knowledge, live)
        self.assertIn('仍然在架', line)
        self.assertIn('不说明它支持得住', line)
        self.assertNotIn('后来已被换掉', line)

    def test_pending_source_is_its_own_sentence(self):
        old = self.q.record('tool_result', {'status': 'executed', 'result': {'note': 'x'}})
        pending = self.q.record('knowledge_proposal', {'synthetic': True, 'proposal': PROPOSAL})
        # `link` records the review cause on the *conclusion*: a later event that
        # leans on a premise is what reopens, not the premise itself.
        self.q.dependencies.link(pending, [old])
        newer = self.q.record('tool_result', {'status': 'executed', 'result': {'note': 'y'}})
        self.q.dependencies.revise(old, newer, 'a later reading replaced it')
        self.assertEqual('needs_review', self.q.dependencies.status(pending)['state'])
        line = cited_source_state(self.q.knowledge, pending)
        self.assertIn('还在等复核', line)
        self.assertNotIn('仍然在架', line)
        self.assertNotIn('后来已被换掉', line)

    def test_unreadable_is_not_reported_as_valid_or_invalid(self):
        line = cited_source_state(self.q.knowledge, 999999)
        self.assertIn('找不到', line)
        self.assertIn('不说它有效，也不说它失效', line)

    def test_the_four_sentences_are_all_different(self):
        """The whole point: four facts must not print the same words."""
        live = self.q.record('tool_result', {'status': 'executed', 'result': {'note': 'a'}})
        old = self.q.record('tool_result', {'status': 'executed', 'result': {'note': 'b'}})
        new = self.q.record('tool_result', {'status': 'executed', 'result': {'note': 'c'}})
        self.q.dependencies.revise(old, new, 'replaced')
        premise = self.q.record('tool_result', {'status': 'executed', 'result': {'note': 'd'}})
        pending = self.q.record('knowledge_proposal', {'synthetic': True, 'proposal': PROPOSAL})
        self.q.dependencies.link(pending, [premise])
        self.q.dependencies.revise(premise, self.q.record('tool_result', {'status': 'executed', 'result': {'note': 'e'}}),
                                   'replaced')
        lines = [cited_source_state(self.q.knowledge, e) for e in (live, old, pending, 999999)]
        self.assertEqual(4, len(set(lines)), lines)


class ModelInputTests(unittest.TestCase):
    """The new sentence is for the screen; the model must see what it saw before."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = Inquiry(Path(self.tmp.name) / 'db',
                         SimpleNamespace(config=SimpleNamespace(model='deepseek-flash', api_key=None)),
                         synthetic=True)
        self.user = self.q.record('user', {'text': 'Reuse decisions with stated conditions', 'synthetic': True})
        self.q.user_sources[self.user] = 'Reuse decisions with stated conditions'
        self.q.visible_source_text[self.user] = 'Reuse decisions with stated conditions'
        self.source = self.q.record('tool_result', {'status': 'executed', 'result': {'matches': 1}})
        self.q.visible_source_text[self.source] = 'matches'
        self.q.questions.apply(self.q, {
            'kind': 'map_inquiry',
            'questions': [{'key': 'root', 'text': 'What must a handoff retain?', 'parents': [],
                           'origin_event': self.user, 'origin_quote': 'Reuse decisions', 'revises': None}],
            'links': [{'question': 'root', 'proposition': None, 'source_event': self.source,
                       'quote': 'matches', 'relation': 'context', 'explanation': 'context only'}],
            'prediction': 'Organize uncertainties'})

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def test_screen_has_the_sentence_but_model_input_does_not(self):
        screen = self.q.questions.view(story=self.q.story, synthetic=True)['nodes'][0]
        self.assertIn('cited_source', screen['annotations'][0])
        model = self.q.question_context()
        for node in model['nodes']:
            for annotation in node['annotations']:
                self.assertNotIn('cited_source', annotation)


if __name__ == '__main__':
    unittest.main()
