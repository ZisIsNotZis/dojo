"""One explicit, budgeted continuation of an existing story without new testimony."""
from types import SimpleNamespace

from .inquiry import Inquiry,config_from_pi,make_client,validate_distillation
from .live import LiveError
from .stories import prepare_resume,run_index


def distillation_delta(db,story):
    """Chronological work marker, not a claim that previous understanding was right."""
    runs={run for run,item in run_index(db).items() if item['story']==story}
    attempt=None;material=None
    for seq,run,kind in db.execute("SELECT seq,run,kind FROM inquiry_events WHERE kind IN ('user','tool_result','delivered','distill_request_started') ORDER BY seq"):
        if run not in runs:continue
        if kind=='distill_request_started':attempt=seq
        else:material=seq
    needed=material is not None and (attempt is None or material>attempt)
    return {'needed':needed,'last_attempt_event':attempt,'last_material_event':material,
        'reason':'new_material' if needed else 'no_new_material_since_attempt',
        'scope':'Chronology only; skips repeated initial distillation, including failed attempts. Does not certify prior intent or knowledge.'}


class _OfflineClient:
    config=SimpleNamespace(model='deepseek-flash',api_key=None)
    json_output=False
    def complete(self,*args,**kwargs):
        raise LiveError('零模型预算维护不能调用模型',kind='budget')


def run_maintenance(path,story,*,synthetic=False,max_requests=4,max_tools=1,retry_distillation=False,retry_associations=False):
    if type(max_requests) is not int or not 0<=max_requests<=12:raise ValueError('maintenance model budget must be 0..12')
    if type(max_tools) is not int or not 0<=max_tools<=4:raise ValueError('maintenance tool budget must be 0..4')
    if type(synthetic) is not bool or type(retry_distillation) is not bool or type(retry_associations) is not bool:raise ValueError('invalid maintenance options')
    # Invalid/mismatched stories and an absent database must not read credentials,
    # create a database, or consume a model request.
    plan=prepare_resume(path,story,synthetic=synthetic)
    if plan['opening'] is None:raise ValueError('故事尚无用户材料；未启动维护')
    clients={}
    if max_requests:
        from .reviews import validate_review
        from .question_reviews import validate_review as validate_relations
        from .associations import validate as validate_associations
        from .research import validate as validate_research
        config=config_from_pi()
        host=make_client(config)
        clients={name:make_client(config,content_validator=validator) for name,validator in (
            ('review',validate_review),('scribe',validate_distillation),('relations',validate_relations),
            ('associations',validate_associations),('research',validate_research))}
    else:host=_OfflineClient()
    q=Inquiry(path,host,synthetic=synthetic,story=story,request_budget=max_requests,tool_budget=max_tools)
    # Knowledge review is story-scoped, plus upstream targets explicitly reopened
    # from this story. Other existing callers retain their network-wide policy.
    q.review_story=story
    finished=False
    try:
        delta=distillation_delta(q.db,story)
        initial=delta['needed'] or retry_distillation
        q.record('maintenance_started',{'max_requests':max_requests,'max_tools':max_tools,
            'review_scope':'story_and_explicit_upstream_targets','initial_distillation':delta,
            'retry_distillation':retry_distillation,'retry_associations':retry_associations,'new_user_testimony':False})
        result=q.maintain(clients.get('review',host),scribe_client=clients.get('scribe'),
            question_review_client=clients.get('relations'),association_client=clients.get('associations'),
            research_client=clients.get('research'),max_requests=max_requests,reserve_chat=False,distill_initial=initial,retry_associations=retry_associations)
        summary={'status':'pass_finished','run':q.run,'story':story,'synthetic':synthetic,
            'requests_used':max_requests-q.requests,'tools_used':max_tools-q.tools,
            'remaining_requests':q.requests,'remaining_tools':q.tools,
            'initial_distillation':{'scheduled':bool(max_requests and initial),'forced':retry_distillation,**delta},'result':result,
            'review_scope':'story_and_explicit_upstream_targets','retry_associations':retry_associations,'truth':'not_certified'}
        q.record('maintenance_finished',summary);finished=True
        return summary
    finally:
        q.record('end',{'reason':'maintenance_pass' if finished else 'maintenance_interrupted',
            'remaining_requests':q.requests,'remaining_tools':q.tools})
        q.close()
