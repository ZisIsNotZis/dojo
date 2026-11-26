"""Bound request views by omitting labelled historical source bodies, never raw events."""
import copy
import json


def pack(messages,*,limit=120000,target=90000):
    if type(limit) is not int or type(target) is not int or not 0<target<=limit:raise ValueError('invalid context bounds')
    before=sum(len(m['content']) for m in messages)
    if before<=limit:return messages,{'status':'unchanged','characters':before}
    packed=copy.deepcopy(messages);documents=[];candidates=[]
    for index,message in enumerate(packed):
        if message['role']!='user':continue
        content=message['content'];offset=0 if content.startswith('{') else content.find('\n{')+1
        if offset<=0 and not content.startswith('{'):continue
        try:value=json.loads(content[offset:])
        except (ValueError,TypeError):continue
        if not isinstance(value,dict):continue
        # Only program-built catalogs: ordinary user prose and actual tool
        # receipt messages are not parsed or replaced by this projection.
        key='source_catalog' if 'user_event' in value and isinstance(value.get('source_catalog'),list) else ('sources' if 'previous_run' in value and isinstance(value.get('sources'),list) else None)
        if key is None:continue
        doc={'index':index,'prefix':content[:offset],'value':value};documents.append(doc)
        for source in value[key]:
            if not isinstance(source,dict) or 'text' not in source or source.get('kind')=='user':continue
            # Preserve current user statements. Older model explanations go
            # first, then older historical tool bodies; metadata stays visible.
            priority=0 if source.get('kind') in {'reflection','epistemic_check'} else 1
            candidates.append((priority,source.get('event',0),source,doc))
    omitted=[];after=before
    for _,event,source,doc in sorted(candidates,key=lambda c:(c[0],c[1])):
        if after<=target:break
        removed=[key for key in ('text','proposal') if key in source]
        if not removed:continue
        for key in removed:source.pop(key)
        source['body_omitted_for_context_limit']=True
        doc['value']['context_projection']={'scope':'Historical source bodies omitted explicitly; current user statements and raw ledger retained. Omission is not a new fact or a truth verdict. Do not invent omitted content or claim this view is complete.'}
        packed[doc['index']]['content']=doc['prefix']+json.dumps(doc['value'],ensure_ascii=False)
        after=sum(len(m['content']) for m in packed);omitted.append({'message':doc['index'],'event':event,'fields':removed})
    omitted_events={item['event'] for item in omitted}
    retained_events={source.get('event') for doc in documents for key in ('sources','source_catalog') for source in doc['value'].get(key,[]) if isinstance(source,dict) and 'text' in source}
    hidden=omitted_events-retained_events;removed_anchors=0
    for doc in documents:
        anchors=doc['value'].get('citation_anchors')
        if not isinstance(anchors,list):continue
        shown=[a for a in anchors if a.get('source_event') not in hidden]
        removed_anchors+=len(anchors)-len(shown);doc['value']['citation_anchors']=shown
        packed[doc['index']]['content']=doc['prefix']+json.dumps(doc['value'],ensure_ascii=False)
    after=sum(len(m['content']) for m in packed)
    return packed,{'status':'packed' if after<=limit else 'insufficient_space','characters_before':before,'characters_after':after,'limit':limit,'target':target,'omitted_historical_bodies':omitted,'citation_anchors_suppressed':removed_anchors}
