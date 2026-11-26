"""Bounded exact citation choices over displayed source observations."""
import json

CONTRACT='verified_observation_anchors_v1'
# The only source kinds a premise may cite. Defined here so the anchor catalog
# and knowledge.check share one literal: an anchor on a kind outside this set is
# a citation the reviewer can select and never use (knowledge.py refuses it).
CITABLE_KINDS=frozenset({'user','tool_result','knowledge_proposal','reflection'})

# Keys a digest must not cover. `at` is immutable per event, so it never
# distinguishes two reviews of the same material. `review_attempts` is the history
# of attempts *on* this content: including it would change the very digest the
# retry exclusion compares against, so a parked proposal would be offered again on
# every scan (measured on a real db: 9b7761bf14efe6f0 -> f5596684479399bb). Both
# are read by reviewers but neither is content, so neither belongs in the digest
# that answers whether this is the same material.
DIGEST_NEUTRAL_KEYS=frozenset({'at','review_attempts'})

def strip_times(value):
    """Drop digest-neutral keys at any depth: a digest identifies content.

    `at` is immutable per event, so it never distinguishes two reviews of the
    same material; including it only made digests recorded before sources
    carried `at` stop matching, which silently re-opened reviewed proposals.
    """
    if isinstance(value,dict):return {k:strip_times(v) for k,v in value.items() if k not in DIGEST_NEUTRAL_KEYS}
    if isinstance(value,list):return [strip_times(v) for v in value]
    return value

def packet_hash(packet):
    import hashlib
    body={k:v for k,v in packet.items() if k!='sha256'}
    return hashlib.sha256(json.dumps(strip_times(body),ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def source_hash(source):
    """Keep this in sync with packet_hash: reviewers hash sources too."""
    return packet_hash(source)

def anchor_catalog(knowledge,sources,*,exclude_events=(),max_characters=24000):
    anchors=[];characters=0;groups=[]
    for source in sources:
        # Withhold any anchor knowledge.check would refuse as a premise source:
        # a citation the reviewer can select and never use is a visible promise
        # with no way to keep it. `falsifier_hit` (bookkeeping) and
        # `question_evidence` (organization) both sit outside CITABLE_KINDS, so
        # both are withheld by the same rule. The event stays a source
        # (review_context.causes reads it); only the anchor is withheld.
        if source['event'] in exclude_events or source['kind'] not in CITABLE_KINDS or source['dependency_status']['state']!='current_interpretation':continue
        raw=knowledge.source(source['event'])['text']
        text=knowledge.observed_tool_text(source['event']) if source['kind']=='tool_result' else source['text']
        snippets=[]
        if source['kind']=='tool_result' and text:
            result=json.loads(text)
            payload=json.loads(raw)
            if payload.get('action',{}).get('kind') in {'check_design','check_entailment','check_progress'} and len(text)<=2000:
                # Rank alone does not say whether this specific contrast is
                # identified. Keep the computed certificate together when it
                # fits; no action, model terms or assumptions are copied here.
                snippets.append(([],text))
            if isinstance(result,dict):
                def numerical(section,path,limit,examples=False):
                    for key in ('counterexample_count','evaluated','passed'):
                        if key in section:snippets.append((path+[key],json.dumps(key)+': '+json.dumps(section[key])))
                    if section.get('binary_derived_counts'):
                        snippets.append((path+['binary_derived_counts'],'"binary_derived_counts": '+json.dumps(section['binary_derived_counts'],ensure_ascii=False,sort_keys=True)))
                    if examples:
                        for key in ('passing_examples','counterexamples'):
                            snippets.extend((path+[key,index],json.dumps(item,ensure_ascii=False,sort_keys=True)) for index,item in enumerate(section.get(key,[])[:2]))
                    parts=section.get('component_checks',[])
                    if not isinstance(parts,list):return
                    indexed=[(i,c) for i,c in enumerate(parts) if isinstance(c,dict)]
                    # Offer failures first, without changing their original
                    # component indices or joining fields across JSON parents.
                    indexed.sort(key=lambda pair:(not(type(pair[1].get('counterexample_count')) is int and pair[1]['counterexample_count']>0),pair[0]))
                    for index,component in indexed[:limit]:snippets.append((path+['component_checks',index],json.dumps(component,ensure_ascii=False,sort_keys=True)))
                for stage in ('original','tolerant'):
                    section=result.get(stage)
                    if not isinstance(section,dict):continue
                    numerical(section,[stage],4)
                if 'evaluated' in result and 'passed' in result:
                    numerical(result,[],6,examples=True)
                # Keep the exact JSON escaping/newlines. The model selects an
                # integer; it never has to retype or flatten the source string.
                for index,item in enumerate(result.get('sources',[]) if isinstance(result.get('sources'),list) else []):
                    if isinstance(item,dict) and isinstance(item.get('excerpt'),str):
                        snippets.append((['sources',index,'excerpt'],'"excerpt": '+json.dumps(item['excerpt'],ensure_ascii=False)))
                for key in ('passing_examples','counterexamples','sample_points'):
                    snippets.extend(([key,index],json.dumps(p,ensure_ascii=False,sort_keys=True)) for index,p in enumerate(result.get(key,[])[:10]))
                for key,value in result.items():
                    if key not in {'passing_examples','sample_points','counterexamples','arms','sources','original','tolerant','component_checks','evaluated','passed','counterexample_count'}:snippets.append(([key],json.dumps(key,ensure_ascii=False)+': '+json.dumps(value,ensure_ascii=False,sort_keys=True)))
                for arm in result.get('arms',[]):
                    if 'literal_counts' in arm:snippets.append('"literal_counts": '+json.dumps(arm['literal_counts'],ensure_ascii=False,sort_keys=True))
        else:snippets=[text[i:i+1500] for i in range(0,len(text),1500)]
        seen=set();group=[]
        for snippet in snippets:
            path,quote=snippet if isinstance(snippet,tuple) else (None,snippet)
            signature=(quote,tuple(path or ()))
            if not quote or len(quote)>2000 or signature in seen or quote not in text or quote not in raw or len(quote)>max_characters:continue
            group.append({'source_event':source['event'],'quote':quote,**({'observation_path':path} if path is not None else {})});seen.add(signature)
            if len(group)>=14:break
        if group:groups.append(group)
    # Give distinct sources a turn before offering further fields from one
    # receipt. Otherwise a handful of old tools can consume every handle and
    # make newer observations impossible to cite despite being displayed.
    for depth in range(14):
        for group in groups:
            if depth>=len(group):continue
            item=group[depth]
            if characters+len(item['quote'])>max_characters:continue
            anchors.append({'anchor':len(anchors)+1,**item});characters+=len(item['quote'])
            if len(anchors)>=64:return anchors
    return anchors

def proposal_for_validation(proposal):
    """Check the citation envelope without inventing any actual source identity."""
    if not isinstance(proposal,dict):return proposal
    premises=proposal.get('premises')
    if not isinstance(premises,list) or not any(isinstance(p,dict) and 'anchor' in p for p in premises):return proposal
    normalized=[]
    for premise in premises:
        if not isinstance(premise,dict) or set(premise)!={'anchor','role'} or type(premise['anchor']) is not int or premise['anchor']<=0:raise ValueError('invalid anchored premise')
        normalized.append({'event':1,'quote':'anchor','role':premise['role']})
    return {**proposal,'premises':normalized}

def resolve_proposal(packet,proposal):
    # Raw legacy citations remain exact: never normalize their whitespace.
    if not any('anchor' in p for p in proposal['premises']):return proposal
    proposal_for_validation(proposal)
    premises=[]
    for premise in proposal['premises']:
        anchor=resolve_anchor(packet,premise['anchor'])
        premises.append({'event':anchor['source_event'],'quote':anchor['quote'],'role':premise['role']})
    return {**proposal,'premises':premises}

def resolve_anchor(packet,index):
    if type(index) is not int or index<=0:raise ValueError('invalid review anchor')
    anchor=next((a for a in packet.get('anchors',[]) if a['anchor']==index),None)
    if anchor is None:raise ValueError('unseen review anchor')
    source=next((s for s in packet['sources'] if s['event']==anchor['source_event']),None)
    if source is None or source['dependency_status']['state']!='current_interpretation' or anchor['quote'] not in source['text']:raise ValueError('review anchor not current or displayed')
    return anchor

class FrontendAnchors:
    """Monotonic handles scoped to one run; only newly offered entries are sent."""
    def __init__(self,run):self.run=run;self.entries={};self.signatures={}

    @staticmethod
    def source_hash(source):return packet_hash(source)

    def offer(self,knowledge,sources):
        current={s['event']:knowledge.source(s['event']) for s in sources if s['kind'] in {'user','tool_result','knowledge_proposal','reflection','epistemic_check'}}
        added=[]
        for item in anchor_catalog(knowledge,current.values()):
            source=current[item['source_event']];digest=self.source_hash(source)
            signature=(item['source_event'],item['quote'],tuple(item.get('observation_path',[])),digest)
            if signature in self.signatures:continue
            index=len(self.entries)+1
            value={**item,'anchor':index,'source_kind':source['kind'],'source_hash':digest,
                'allowed_relations':['context'] if source['kind'] in {'reflection','epistemic_check'} else ['context','supports','challenges']}
            self.entries[index]=value;self.signatures[signature]=index;added.append(value)
        return added

    def resolve(self,knowledge,index,visible,*,relation,synthetic):
        if type(index) is not int or index not in self.entries:raise ValueError('unseen frontend anchor')
        entry=self.entries[index];event=entry['source_event']
        if event not in visible or entry['quote'] not in visible[event]:raise ValueError('frontend anchor not displayed')
        source=knowledge.source(event)
        if source['dependency_status']['state']!='current_interpretation' or self.source_hash(source)!=entry['source_hash']:raise ValueError('frontend anchor changed')
        if not synthetic and knowledge.dependencies._synthetic(event):raise ValueError('synthetic frontend anchor')
        if relation not in entry['allowed_relations']:raise ValueError('frontend model anchor only provides context')
        if entry['quote'] not in source['text']:raise ValueError('frontend anchor quote mismatch')
        if source['kind']=='tool_result' and entry['quote'] not in knowledge.observed_tool_text(event):raise ValueError('frontend input is not an observation')
        return entry
