"""Bounded audit when old tool envelopes exposed model inputs as observations."""
import json
from datetime import datetime,timezone
from .stories import run_index

POLICY='computed_tool_observations_v2'


def audit_observation_anchors(q,*,limit=8):
    if type(limit) is not int or not 0<=limit<=64:raise ValueError('invalid grounding audit limit')
    scope={run for run,item in run_index(q.db).items() if item['story']==q.story and item['synthetic'] is q.synthetic}
    done=set()
    for (payload,) in q.db.execute("SELECT payload FROM inquiry_events WHERE kind='observation_anchor_audit'"):
        item=json.loads(payload)
        if item['policy']==POLICY:done.add(item['target'])
    issues=[]
    for event,run,kind,payload in q.db.execute("SELECT seq,run,kind,payload FROM inquiry_events WHERE kind IN ('knowledge_proposal','question_evidence') ORDER BY seq"):
        if len(issues)>=limit:break
        if run not in scope or event in done or q.dependencies.status(event)['state']=='superseded':continue
        data=json.loads(payload)
        if kind=='knowledge_proposal':anchors=[p for p in data['proposal']['premises'] if p['role']=='evidence']
        else:anchors=[{'event':data['source_event'],'quote':data['quote']}] if data['relation']!='context' else []
        invalid=sorted({p['event'] for p in anchors if q.knowledge.source(p['event'])['kind']=='tool_result' and p['quote'] not in q.knowledge.observed_tool_text(p['event'])})
        if invalid:issues.append({'target':event,'target_kind':kind,'invalid_observation_sources':invalid})
    with q.db:
        for issue in issues:
            payload={**issue,'policy':POLICY,'story':q.story,'synthetic':q.synthetic,'meaning':'anchor_is_model_input_or_generated_text_not_computed_observation; proposition_truth_not_decided'}
            q.db.execute('INSERT INTO inquiry_events(run,kind,payload,at) VALUES(?,?,?,?)',(q.run,'observation_anchor_audit',json.dumps(payload,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
            for source in issue['invalid_observation_sources']:
                q.db.execute('INSERT OR IGNORE INTO inquiry_review_queue(event,cause) VALUES(?,?)',(issue['target'],source))
    q.dependencies.drain(8)
    return {'policy':POLICY,'marked':issues,'limit':limit}
