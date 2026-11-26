"""Closed-scope execution accounting, separate from claims about tool results."""
import json
from .stories import run_index
from .tool_schema import HOST_TOOLS


def ledger(q,*,through_event=None):
    if through_event is None:
        through_event=q.db.execute('SELECT COALESCE(MAX(seq),0) FROM inquiry_events').fetchone()[0]
    if type(through_event) is not int or through_event<0:raise ValueError('invalid execution cutoff')
    runs=run_index(q.db)
    scope={run for run,item in runs.items() if item['story']==q.story and item['synthetic'] is q.synthetic and item['start_event']<=through_event}
    names=[tool['function']['name'] for tool in HOST_TOOLS]
    counts={name:{status:0 for status in ('executed','failed','not_executed')} for name in names}
    current={name:dict(statuses) for name,statuses in counts.items()}
    recent={};unknown=0
    for event,run,raw in q.db.execute("SELECT seq,run,payload FROM inquiry_events WHERE kind='tool_result' AND seq<=? ORDER BY seq",(through_event,)):
        if run not in scope:continue
        payload=json.loads(raw);tool=payload.get('action',{}).get('kind');status=payload.get('status')
        if tool not in counts or status not in counts[tool]:
            unknown+=1;continue
        counts[tool][status]+=1
        if run==q.run:current[tool][status]+=1
        receipt={'event':event,'run':run,'tool':tool,'status':status,'current_run':run==q.run}
        result=payload.get('result')
        # An executed wrapper does not imply all stages of its result completed.
        if isinstance(result,dict) and isinstance(result.get('status'),str):receipt['result_status']=result['status']
        if isinstance(payload.get('error_kind'),str):receipt['error_kind']=payload['error_kind']
        key=(tool,status);recent.setdefault(key,[]).append(receipt);recent[key]=recent[key][-2:]
    receipts=sorted((item for values in recent.values() for item in values),key=lambda r:r['event'])
    return {'story':q.story,'current_run':q.run,'synthetic':q.synthetic,'through_event':through_event,
        'story_counts':counts,'current_run_counts':current,'unclassified_receipts':unknown,
        'recent_receipts_per_tool_status':receipts,'receipt_limit_per_tool_status':2,
        'scope':'Complete counts of recorded tool_result events in this story/identity through cutoff; receipt excerpts bounded. Plans, tool_started, assistant claims, and background associations do not count as completed calls. Other stories and later events excluded. Zero executed proves no recorded execution in this scope, not no execution anywhere.',
        'limits':'executed proves only runner completion, not result truth, full-text reading, successful real-world effects, or semantic validity. Inspect original receipts for contents; result_status may report incomplete stages.'}
