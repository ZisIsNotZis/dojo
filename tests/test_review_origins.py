import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from dojo.anchors import packet_hash
from dojo.inquiry import Inquiry
from dojo.reviews import perform_rechecks,review_origin_view
from tests.test_knowledge import Client,proposal


class ReviewOriginTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
        old=Inquiry(self.path,Client(),synthetic=True)
        self.old_run=old.run;self.old_story=old.story
        self.first=old.record('user',{'text':'HISTORICAL_BODY_SENTINEL setup initially zero','synthetic':True})
        original=old.record('tool_result',{'status':'executed','result':{'value':48}})
        self.target=old.knowledge.accept(old.run,proposal('A conditional old-case cost',original,'"value": 48'),{original},synthetic=True)
        self.report=old.record('user',{'text':'HISTORICAL_BODY_SENTINEL setup is now 100','synthetic':True})
        new=old.record('tool_result',{'status':'executed','result':{'value':-52}})
        old.knowledge.request_review(old.run,self.target,[self.report,new],'A changed historical cost',{self.target,self.report,new},synthetic=True)
        old.close();self.q=Inquiry(self.path,Client(),synthetic=True,request_budget=1)

    def tearDown(self):self.q.close();self.tmp.cleanup()

    def test_worker_receives_sidecar_and_exact_unchanged_canonical_packet(self):
        canonical=self.q.knowledge.review_packet(self.target);captured=[]
        def complete(messages):
            captured.extend(messages)
            self.assertEqual(canonical,json.loads(messages[-1]['content']))
            self.assertEqual(canonical['sha256'],packet_hash(json.loads(messages[-1]['content'])))
            origins=json.loads(messages[-2]['content'])['review_source_attributions']
            report=next(s for s in origins['sources'] if s['event']==self.report)
            self.assertEqual('other_story',report['story_scope'])
            self.assertEqual('historical_report_not_current_user_testimony',report['attribution'])
            self.assertEqual(self.old_story,report['origin_story'])
            self.assertNotIn('HISTORICAL_BODY_SENTINEL',json.dumps(origins))
            return {'disposition':'unresolved','reason':'Historical report, still hypothetical inputs','replacement':None}
        outcome=perform_rechecks(self.q,SimpleNamespace(complete=complete),max_requests=1)
        self.assertEqual(1,outcome['requests_used']);self.assertEqual(3,len(captured))
        attempt=json.loads(self.q.db.execute("SELECT payload FROM inquiry_events WHERE kind='review_request_started' ORDER BY seq DESC").fetchone()[0])
        self.assertEqual(packet_hash(attempt['source_attributions']),attempt['source_attribution_sha256'])
        # r63: the review just recorded an attempt on this very packet. What the
        # reader gets must be the offered packet plus exactly that record, and the
        # digest must not move -- a moving digest would un-suppress the packet the
        # attempt was recorded against.
        after=self.q.knowledge.review_packet(self.target)
        self.assertIn('review_attempts',after)
        self.assertEqual(1,len(after['review_attempts']))
        self.assertEqual('unresolved',after['review_attempts'][0]['disposition'])
        self.assertEqual(canonical['sha256'],after['sha256'])
        self.assertEqual(canonical,{k:v for k,v in after.items() if k!='review_attempts'})

    def test_creation_here_does_not_reassign_the_quoted_report(self):
        new=self.q.knowledge.accept(self.q.run,proposal('Current-story interpretation of old material',self.report,'HISTORICAL_BODY_SENTINEL setup'),{self.report},synthetic=True)
        packet=self.q.knowledge.review_packet(new);before=copy.deepcopy(packet)
        view=review_origin_view(self.q,packet)
        self.assertEqual('same_story',view['target']['story_scope'])
        premise=view['target']['premise_sources'][0]
        self.assertEqual('other_story',premise['story_scope'])
        self.assertEqual('historical_report_not_current_user_testimony',premise['attribution'])
        self.assertEqual(before,packet)

    def test_origin_mapping_change_discards_when_canonical_sources_are_unchanged(self):
        canonical=self.q.knowledge.review_packet(self.target)
        def complete(messages):
            row=json.loads(self.q.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='start'",(self.old_run,)).fetchone()[0]);row['story']=self.q.story
            with self.q.db:self.q.db.execute("UPDATE inquiry_events SET payload=? WHERE run=? AND kind='start'",(json.dumps(row),self.old_run))
            self.assertEqual(canonical,self.q.knowledge.review_packet(self.target))
            return {'disposition':'unresolved','reason':'Do not apply stale attribution','replacement':None}
        result=perform_rechecks(self.q,SimpleNamespace(complete=complete),max_requests=1)
        self.assertEqual('discarded',result['outcomes'][0]['status'])
        self.assertEqual('source_attribution_changed',result['outcomes'][0]['reason'])
        self.assertEqual(1,len(self.q.knowledge.proposals(synthetic=True)))

    def test_explicit_same_story_review_keeps_reports_in_the_source_story(self):
        self.q.close();self.q=Inquiry(self.path,Client(),synthetic=True,story=self.old_story,request_budget=1)
        view=review_origin_view(self.q,self.q.knowledge.review_packet(self.target))
        report=next(s for s in view['sources'] if s['event']==self.report)
        self.assertEqual('same_story',report['story_scope'])
        self.assertEqual('reported_in_current_story',report['attribution'])

    def relation(self):
        user=self.q.record('user',{'text':'Review the old case without treating it as mine','synthetic':True})
        self.q.user_sources[user]='Review the old case without treating it as mine'
        tool=self.q.knowledge.source(self.target)['proposal']['premises'][0]['event']
        for e in (user,tool,self.target):self.q.visible_source_text[e]=self.q.knowledge.source(e)['text']
        created=self.q.questions.apply(self.q,{'kind':'map_inquiry','questions':[{'key':'r','text':'What does the historical result support?','parents':[],'origin_event':user,'origin_quote':'Review the old case','revises':None}],
            'links':[{'question':'r','proposition':self.target,'source_event':tool,'quote':'48','relation':'context','explanation':'Old model only'}],'prediction':'Keep provenance distinct'})
        return created['graph']['nodes'][0]['annotations'][0]['event']

    def test_relation_worker_receives_origins_for_nested_pending_report(self):
        from dojo.question_reviews import perform_rechecks as relations,review_packet
        target=self.relation();canonical=review_packet(self.q,target)
        def complete(messages):
            self.assertEqual(canonical,json.loads(messages[-1]['content']))
            view=json.loads(messages[-2]['content'])['review_source_attributions']
            claim=next(s for s in view['sources'] if s['event']==self.target)
            report=next(s for s in claim['review_signals'] if s['event']==self.report)
            self.assertEqual('other_story',report['story_scope'])
            self.assertEqual('historical_report_not_current_user_testimony',report['attribution'])
            return {'disposition':'unresolved','reason':'Pending historical case remains uncertain','replacement':None}
        result=relations(self.q,SimpleNamespace(complete=complete),max_requests=1)
        self.assertEqual('reviewed',result['outcomes'][0]['status'])
        self.assertEqual('unresolved',result['outcomes'][0]['disposition'])

    def test_relation_origin_change_discards_without_mutating_the_relation(self):
        from dojo.question_reviews import perform_rechecks as relations,review_packet
        target=self.relation();canonical=review_packet(self.q,target)
        def complete(messages):
            row=json.loads(self.q.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='start'",(self.old_run,)).fetchone()[0]);row['story']=self.q.story
            with self.q.db:self.q.db.execute("UPDATE inquiry_events SET payload=? WHERE run=? AND kind='start'",(json.dumps(row),self.old_run))
            self.assertEqual(canonical,review_packet(self.q,target))
            return {'disposition':'unresolved','reason':'Do not use stale origins','replacement':None}
        result=relations(self.q,SimpleNamespace(complete=complete),max_requests=1)
        self.assertEqual('source_attribution_changed',result['outcomes'][0]['reason'])
        self.assertNotEqual('superseded',self.q.dependencies.status(target)['state'])


if __name__=='__main__':unittest.main()
