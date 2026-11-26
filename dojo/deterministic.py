"""Recompute legacy numeric observations before narrowing context invalidation."""
import hashlib
import json
from datetime import datetime,timezone
from .experiments import expression,parameter_sweep
from .knowledge import tool_observation_text
from .stories import run_index

POLICY='fixed_input_numeric_observation_v1'


def revalidate_context(q,*,max_attempts=1):
    if type(max_attempts) is not int or not 0<=max_attempts<=4:raise ValueError('invalid numeric revalidation budget')
    scope={run for run,item in run_index(q.db).items() if item['story']==q.story and item['synthetic'] is q.synthetic}
    attempted=set()
    for (payload,) in q.db.execute("SELECT payload FROM inquiry_events WHERE kind IN ('numeric_context_revalidated','numeric_context_failure')"):
        data=json.loads(payload)
        if data['policy']==POLICY:attempted.add((data['target'],data['packet_sha256']))
    outcomes=[]
    rows=list(q.db.execute("SELECT seq,run,payload FROM inquiry_events WHERE kind='tool_result' ORDER BY seq"))
    for event,run,raw in rows:
        if len(outcomes)>=max_attempts or q.tools<=0:break
        if run not in scope or q.dependencies.status(event)['state']!='needs_review':continue
        payload=json.loads(raw);action=payload.get('action',{})
        if payload.get('status')!='executed' or action.get('kind') not in {'calculate','experiment'}:continue
        plans=[]
        for premise,plan in q.db.execute("SELECT d.premise,e.payload FROM inquiry_dependencies d JOIN inquiry_events e ON e.seq=d.premise WHERE d.conclusion=? AND d.relation='context' AND e.kind='reflection'",(event,)):
            value=json.loads(plan).get('reflection',{})
            if action in value.get('tool_batch',[value.get('action')]):plans.append(premise)
        if not plans:continue
        packet={'payload':payload,'state':q.dependencies.status(event),'plans':plans}
        digest=hashlib.sha256(json.dumps(packet,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if (event,digest) in attempted:continue
        metadata={'target':event,'policy':POLICY,'packet_sha256':digest,'planning_events':plans}
        q.tools-=1
        q.record('numeric_context_attempt',{**metadata,'remaining_tools':q.tools})
        try:
            if action['kind']=='calculate':result={'value':expression(action['expression']),'scope':'仅给定假设下算术，非现实验证'}
            else:result=parameter_sweep(action['parameters'],action['derived'],action['assertion'])
            recomputed={'action':action,'status':'executed','result':result}
            prior=json.loads(tool_observation_text(payload));fresh=json.loads(tool_observation_text(recomputed))
            # New computed diagnostic fields do not change an older observation.
            # Every field actually present in the old receipt must still match.
            if any(key not in fresh for key in prior) or json.dumps(prior,ensure_ascii=False,sort_keys=True)!=json.dumps({key:fresh[key] for key in prior},ensure_ascii=False,sort_keys=True):raise ValueError('computed_observation_changed')
            # Events remain immutable. Only the dependency projection changes,
            # with this explicit replay receipt as its authoritative audit.
            with q.db:
                if q.db.execute('SELECT payload FROM inquiry_events WHERE seq=?',(event,)).fetchone()[0]!=raw:raise ValueError('source_changed_during_replay')
                proof={**metadata,'synthetic':q.synthetic,'story':q.story,'observation_sha256':hashlib.sha256(tool_observation_text(recomputed).encode()).hexdigest(),'comparison_scope':'all_original_observation_fields_identical; additional_computed_diagnostics_allowed','meaning':'same_fixed_inputs_same_computed_observation; applicability_not_verified'}
                q.db.execute('INSERT INTO inquiry_events(run,kind,payload,at) VALUES(?,?,?,?)',(q.run,'numeric_context_revalidated',json.dumps(proof,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
                for plan in plans:q.db.execute("UPDATE inquiry_dependencies SET relation='execution_context' WHERE conclusion=? AND premise=? AND relation='context'",(event,plan))
            outcomes.append({'target':event,'status':'revalidated','dependency_status':q.dependencies.status(event)})
        except (ValueError,TypeError,KeyError,SyntaxError,ArithmeticError) as exc:
            kind=type(exc).__name__
            q.record('numeric_context_failure',{**metadata,'kind':kind})
            outcomes.append({'target':event,'status':'failed','kind':kind})
    return {'tool_attempts_used':len(outcomes),'outcomes':outcomes}
