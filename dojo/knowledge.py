"""Knowledge proposals over quoted events; source grounding is not entailment."""
import hashlib
import json
from datetime import datetime,timezone
from .dependencies import DependencyIndex
from .anchors import CITABLE_KINDS


def record_source_comparison(path, story, target, events, relation, reason, *, synthetic=False):
    """Record an operator's comparison offline, on an explicit existing library."""
    from contextlib import closing
    from pathlib import Path
    import sqlite3
    from .stories import run_index

    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=rw', uri=True)) as db:
            # Keep the current-version check and notice write in one transaction.
            db.execute('BEGIN IMMEDIATE')
            runs = run_index(db)
            row = db.execute('SELECT run FROM inquiry_events WHERE seq=?', (target,)).fetchone()
            owner = runs.get(row[0]) if row else None
            identities = {info['synthetic'] for info in runs.values() if info['story'] == story}
            if owner is None or owner['story'] != story or identities != {synthetic}:
                raise ValueError('提议必须在指定故事及其普通/合成身份内')
            return Knowledge(db, initialize=False).request_review(
                row[0], target, events, reason, {target, *events}, synthetic=synthetic, comparison=relation)
    except (sqlite3.Error, OverflowError):
        raise ValueError('无法在指定库记录比较；请选择已存在且可写的 Dojo 探究库') from None


def _scored_events(db):
    """Proposal ids that some packet-reading writer points at.

    `review_packet` attaches the r37/r60/r61 keys only when a writer names the
    proposal: a hit or a bridge check carries `proposal`, a review attempt
    carries `target`, and a revision's `new_event` carries the inherited
    reading. Any other proposal's packet has none of them, so building it
    buys nothing. Building it anyway cost 2.3 ms per row on
    `inquiry.retrieve_knowledge`, which lists 500 rows per turn.
    """
    seen=set()
    for kind,field in (('falsifier_hit','proposal'),('knowledge_review','target'),
            ('review_failure','target')):
        for (payload,) in db.execute('SELECT payload FROM inquiry_events WHERE kind=?',(kind,)):
            value=json.loads(payload).get(field)
            if value is not None:seen.add(value)
    for (payload,) in db.execute("SELECT payload FROM inquiry_events WHERE kind='falsifier_bridge_checked'"):
        for outcome in json.loads(payload).get('outcomes') or ():
            if isinstance(outcome,dict) and outcome.get('proposal') is not None:seen.add(outcome['proposal'])
    tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'inquiry_revisions' in tables:
        for (new,) in db.execute('SELECT new_event FROM inquiry_revisions'):seen.add(new)
    return seen


def _reopened_since(db,event,after):
    """Is there review work on this packet that is newer than attempt `after`?

    This answers a question the data can actually settle: `needs_review` causes
    carry event ids, and a cause newer than the attempt is work the review did not
    see. It does NOT claim the packet's content changed -- see below, where two
    broader tests were measured and thrown away for saying that when it was false.

    r87: a stored digest can stop matching without the material changing at all --
    the digest *rule* changed. Measured on a real row: the packet rebuilt from the
    database trimmed to the review's own sequence number is byte-identical to
    today's packet (0 structural differences), yet the stored digest differs. So a
    mismatch alone proves nothing, and r63's rule -- skip every attempt whose
    digest differs -- turned 'reviewed under an older rule' into 'never reviewed'
    and offered the packet again.

    Two broader tests were built first and both were wrong, measured against a
    rebuild of the packet on a copy of the database trimmed to each review's own
    sequence number (139 of 146 rows rebuild byte-identically, so that rebuild is
    the oracle):

    - 'any revision written since' fired on 122/146 and was false on 115.
    - 'a dependency edge or mention newer than the attempt' fired on 115 and was
      false on 109. A dependency edge is not content: it records that something
      depends on the proposal, which happens without the packet moving at all.

    Neither could ship: the sentence beside the attempt would have said the material
    may have changed when it had not. This version only reports that newer work on
    this packet exists, and the reading says exactly that and nothing more.
    """
    tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'inquiry_revisions' in tables:
        if db.execute('SELECT 1 FROM inquiry_revisions WHERE new_event>? AND old_event=? LIMIT 1',(after,event)).fetchone():return True
    if 'inquiry_review_queue' in tables:
        if db.execute('SELECT 1 FROM inquiry_review_queue WHERE cause>? AND event=? LIMIT 1',(after,event)).fetchone():return True
    if 'inquiry_dependencies' in tables:
        if db.execute('SELECT 1 FROM inquiry_dependencies WHERE premise=? AND conclusion>? LIMIT 1',(event,after)).fetchone():return True
    for (payload,) in db.execute("SELECT payload FROM inquiry_events WHERE seq>? AND kind IN ('knowledge_proposal','knowledge_withdrawal','review_evidence_notice','falsifier_hit','falsifier_bridge_checked')",(after,)):
        data=json.loads(payload)
        # An affirmative comparison records completed checking, not new work.
        comparison = data.get('comparison')
        if isinstance(comparison, dict) and comparison.get('relation') == 'supports_independently':
            continue
        if data.get('target')==event or data.get('proposal')==event:return True
        if isinstance(data.get('proposal'),dict) and data['proposal'].get('revises')==event:return True
        for outcome in data.get('outcomes') or ():
            if isinstance(outcome,dict) and outcome.get('proposal')==event:return True
    return False


def _unreadable_premises(db,proposal,causes=()):
    """Events this packet needs to be rebuilt that this library no longer holds.

    Walked from the data, not parsed out of an exception message: `unknown
    knowledge source` does not say which event, and an error string is not a
    place to get facts about a record. Same frontier `review_packet` expands --
    premises, nested proposal premises, and the review causes -- so a name that
    comes back here is one the packet genuinely could not read.
    """
    missing=[];queue=[proposal];seen=set()
    for event in causes:
        if type(event) is not int:continue
        if db.execute('SELECT 1 FROM inquiry_events WHERE seq=?',(event,)).fetchone() is None:
            missing.append(event)
    while queue:
        body=queue.pop(0) or {}
        for premise in body.get('premises') or []:
            event=premise.get('event') if isinstance(premise,dict) else None
            if type(event) is not int:continue
            row=db.execute('SELECT kind,payload FROM inquiry_events WHERE seq=?',(event,)).fetchone()
            if row is None:
                missing.append(event);continue
            if event in seen:continue
            seen.add(event)
            if row[0]=='knowledge_proposal':
                try:queue.append(json.loads(row[1])['proposal'])
                except (KeyError,ValueError,TypeError):pass
    return sorted(set(missing))


def _name_events(events):
    """A clause naming the absent events, or a bare 'some statement' clause."""
    if not events:return '它引用的某条语句'
    return '事件 %s ' % '、'.join(str(e) for e in events)


def _content_digest(packet):
    # One definition, shared with apply_review's check: two hashes that disagree
    # about whether `at` counts would make every review look tampered with.
    from .anchors import packet_hash
    return packet_hash(packet)

METHODS={'deduction','induction','analogy','hypothesis'}

# r84: a quote that is one comma is not a citation. Until r84 the only floor was
# `quote.strip()`, so `,` passed on 46 of 60 proposals whose own quotes were
# never prose. The floor counts runs of letters/digits (Han included); punctuation,
# whitespace and JSON syntax glue do not count.
QUOTE_FLOOR_ENV='DOJO_QUOTE_FLOOR'
MIN_QUOTE_RUN=6


def quote_floor():
    """Which citations count as attributable.

    'default' - a 6-character run of letters/digits, OR a verbatim `"key":`
               reference into the event's own JSON. A comma, `[]`, `1`, `48`,
               `-52` and `true` are none of those and are rejected.
               The keyed form is admitted because a computed observation has no
               sentence; it is counted under its own label and never called
               'quoted the words they wrote'.
    'prose'   - only the 6-character run. Field references are rejected, so this
               is the floor to use when counting prose citations alone.
    'legacy'  - any non-blank quote, i.e. the pre-r84 floor. Kept so the older
               readings (146/239, 227/239) stay reproducible.
    """
    import os
    value=os.environ.get(QUOTE_FLOOR_ENV,'').strip().lower()
    if value in {'legacy','any','off'}:return 'legacy'
    if value in {'prose','sentences'}:return 'prose'
    return 'default'


def structured_quote(quote):
    """True when the quote names a JSON key, e.g. `"evaluated": 54`.

    A bare `,` or `48` names nothing and stays rejected: the point of the floor
    is that a citation must point at something a reader can find again.
    """
    import re
    return re.search(r'"[^"\n]{1,80}"\s*:', quote or '') is not None


def citeable_quote(quote,floor=None):
    """One predicate for the gate and for the readings, so they cannot drift."""
    floor=floor or quote_floor()
    if floor=='legacy':return bool((quote or '').strip())
    if longest_content_run(quote)>=MIN_QUOTE_RUN:return True
    return floor=='default' and structured_quote(quote)


def citation_kind(quote):
    """'prose' (a fragment of what was written) or 'field' (a JSON key reference).

    Reported side by side, never summed: `"evaluated": 54` does point at a real
    stored field, and it is still not the sentence the person wrote.
    """
    if structured_quote(quote):return 'field'
    return 'prose' if longest_content_run(quote)>=MIN_QUOTE_RUN else 'none'


# r86: the label a reader gets. The stored value is a machine word; a listing
# that printed `prose`/`field` would ask the reader to learn our vocabulary
# before they could tell 'quoted the words they wrote' from 'named a field'.
#
# The prose label names the source kind on purpose. The first version said
# 'quoted the words they wrote' for every prose quote, which read a model's own
# proposal back as if a person had said it -- the exact overclaim this chain
# exists to stop. Only `user` gets the word '人写的'.
CITATION_READING={'field':'只指向了一个存在的字段，不是一句原话',
    'none':'只有一个符号，定位不到任何内容'}

PROSE_READING={'user':'引用了人写的那句原话',
    'knowledge_proposal':'引用了模型提议里的一句原话（提议不是观测）',
    'reflection':'引用了模型判断里的一句原话（判断不是观测）',
    'epistemic_check':'引用了模型批评里的一句原话（批评不是判真）',
    'tool_result':'引用了工具结果里的一段原文（不是人写的）',
    'inquiry_question':'引用了问题框里的一句原话（整理不是判真）'}
PROSE_READING_DEFAULT='引用了记录里的一段原文（来源未分类）'


def citation_reading(quote,at=None,state=None,source_kind=None,max_characters=80):
    """One readable line for one citation; never a key name or a machine code.

    `quote` is copied, not paraphrased. Whitespace inside it is collapsed and a
    long quote is cut with a marked ellipsis, so the line stays one line in a
    listing; the raw quote is recorded beside it in `premise_events`.
    """
    kind=citation_kind(quote)
    text=' '.join((quote or '').split())
    if len(text)>max_characters:text=text[:max_characters]+'…'
    label=CITATION_READING[kind] if kind!='prose' else PROSE_READING.get(source_kind,PROSE_READING_DEFAULT)
    line='%s「%s」' % (label,text)
    if at:line+='，记录于 %s' % at
    if state=='needs_review':line+='；这条依据本身仍未复核'
    # r92: only `needs_review` used to be said out loud. A citation whose event
    # has since been replaced read exactly like a live one -- same words, same
    # time, nothing to tell the reader the ground moved. Found by comparing a
    # `question_review` row with a `knowledge_review` row on the same quote.
    elif state=='superseded':line+='；这条依据后来已被替换，记录的是它当时的样子'
    return line


def basis_source_state(knowledge,item):
    """What happened to one recorded basis citation *after* the review was written.

    `premise_events` stores `dependency_state` as of the moment the review ran.
    That snapshot cannot age: a review written when its basis was live keeps
    saying so after the basis is replaced, and the stored `reading` is the
    sentence from that day. Measured on real copies: append a revision that
    replaces a premise AFTER the review row exists, and the listing is
    byte-identical to the arm where nothing moved.

    So this recomputes the state from the ledger at read time, and says it as a
    separate sentence. Four outcomes, four sentences: replaced / still standing /
    itself awaiting review / cannot be read. A boolean would collapse 'could not
    be read' with 'still fine', which this chain has already paid for twice.
    Nothing is written; the stored row keeps its bytes.
    """
    event=item.get('event')
    try:
        state=knowledge.dependencies.status(event)['state']
        replacement=knowledge.dependencies.status(event).get('replacement')
    except (ValueError,IndexError):
        return ('这条复核记录所依据的事件（%s）在本库里找不到：读不出来时不说它有效，也不说它失效。' % event)
    if state=='superseded':
        return ('这条复核记录所依据的那句（事件 %s）后来已被换掉，换成了事件 %s：行里留下的是它当时的样子，'
                '它现在已不是当前版本。' % (event,replacement))
    if state=='current_interpretation':
        return ('这条复核记录所依据的那句（事件 %s）至今没被换掉：这只说明它还在架，不说明它支持得住。' % event)
    if state=='needs_review':
        return ('这条复核记录所依据的那句（事件 %s）现在本身在等复核：它既没被换掉，也还没站住。' % event)
    return ('这条复核记录所依据的那句（事件 %s）状态未分类（库内状态 %r）：读不出来时不说它有效，也不说它失效。'
            % (event,state))


BASIS_ITEM_FIELDS=('event','at','reading','citation_kind','role','quote')
# r99: a relation row's subject is a relation, and its label is stored under
# `relation` (never `role` -- q_reviews.py says why at length). The gap test
# must therefore take the field list it is judging rather than assume the
# knowledge row's; sharing the *test* is what keeps the two rows comparable,
# and forcing one key name on both would be the defect r92 named.
RELATION_BASIS_ITEM_FIELDS=('event','at','reading','citation_kind','relation','quote')


def basis_gaps(stored,readings=None,fields=BASIS_ITEM_FIELDS):
    """What a recorded basis list does not hold. Empty list means it holds all of it.

    Three ways a row can carry a basis list and still leave a reader unable to
    check it: an entry whose quote locates nothing (a bare number, a comma), an
    entry missing a field the listing reads, and fewer recorded readings than
    entries. Each is said as its own sentence, naming the entry, because
    'incomplete' as a word would fold three different gaps into one and the
    reader could not tell which one to go and look at.
    """
    gaps=[]
    for index,item in enumerate(stored):
        if not isinstance(item,dict):
            gaps.append('这条复核记录的第 %d 条依据不是一个条目：读不出它指向哪个事件。' % (index+1));continue
        event=item.get('event')
        missing=[key for key in fields if key not in item]
        if missing:
            gaps.append('这条复核记录所依据的第 %d 条（事件 %s）缺 %s：这段依据记不全。'
                        % (index+1,event,'、'.join(missing)))
        quote=item.get('quote')
        if isinstance(quote,str) and not citeable_quote(quote):
            # Not 'wrong basis': a quote that names nothing cannot be found again
            # by a reader, which is a gap in the record, not a verdict on the row.
            gaps.append('这条复核记录所依据的第 %d 条（事件 %s）的引文定位不到任何内容：记下的是「%s」。'
                        % (index+1,event,' '.join(quote.split())[:80] or '空'))
    if readings is not None and len(readings)<len(stored):
        gaps.append('这条复核记录记了 %d 条依据，但只留下 %d 条读出：有 %d 条没有当天的读法。'
                    % (len(stored),len(readings),len(stored)-len(readings)))
    return gaps


def outcome_chain_tail(knowledge,event):
    """Follow `inquiry_revisions` forward from `event`.

    Returns `(tail,hops,ended)`:
      ended='live'   chain stops at `tail`, which is still the current version
      ended='cycle'  the walk came back to an event it had already seen
      ended='unreadable'  `event` itself is not in this library

    `hops` counts replacements that happened *after* `event`; 0 means `event`
    is still current. Revisions normally point to a later event (`revise`
    rejects new<=old) so the walk ends, but a hand-edited or restored library
    can hold a loop; that must be said out loud, never printed as 'the chain
    ends at X'. Measured (r96 negative control on a COPY): an inserted loop is
    reachable and the two answers must differ.
    """
    if type(event) is not int:return None,None,'unreadable'
    if knowledge.db.execute('SELECT 1 FROM inquiry_events WHERE seq=?',(event,)).fetchone() is None:
        return None,None,'unreadable'
    seen={event};cur=event;hops=0
    while True:
        row=knowledge.db.execute('SELECT new_event FROM inquiry_revisions WHERE old_event=?',(cur,)).fetchone()
        if row is None:return cur,hops,'live'
        nxt=row[0]
        if nxt in seen:return nxt,hops,'cycle'
        seen.add(nxt);cur=nxt;hops+=1


def outcome_source_state(knowledge,item,kind='knowledge_review'):
    """What happened to the version *this review produced*, read from the ledger now.

    A review row carries `replacement_event`: the version it created. The listing
    printed `disposition` ('retain'/'replace') and nothing about that version
    afterwards, so a review whose own conclusion was later replaced still read as
    a live verdict. Measured on the stored rows (r95): 22 of 146 `knowledge_review`
    and 15 of 104 `question_review` rows name an outcome event that is itself in
    `inquiry_revisions.old_event`.

    Four different situations, four different sentences -- never a boolean:
      superseded / still standing / the outcome event cannot be read here /
      this row recorded no outcome at all (unresolved, unchanged content).
    'Cannot read it' must not come out as 'nothing happened to it', and 'no
    outcome was recorded' must not come out as either.
    """
    if kind=='review_failure':
        return '这次复核没有完成，所以这行上没有它产出的版本：也就无所谓后来有没有被换掉。'
    event=item.get('replacement_event')
    if event is None:
        return ('这次复核没有产出新版本（撤回或内容未变）：这行上没有可被后来换掉的产出，'
                '这不是「产出的版本还活着」。')
    try:
        state=knowledge.dependencies.status(event)
    except (ValueError,IndexError):
        return ('这次复核产出的那个版本（事件 %s）在本库里读不出来：读不出来时不说它还在，也不说它已被换掉。'
                % event)
    if state['state']=='superseded':
        # r96: the successor this row names may itself have been replaced since.
        # Measured on the stored corpus: `2026-11-13-intent-focus/live/baseline`
        # has review 171 -> 170 -> 294 -> 523, so '换成了事件 294' was already
        # stale when printed and the reader could not tell. Say how far the
        # chain runs and name where it stops; one hop keeps the old sentence.
        successor=state.get('replacement')
        tail,hops,ended=outcome_chain_tail(knowledge,successor)
        if ended=='unreadable':
            return ('这次复核产出的那个版本（事件 %s）后来也被换掉了，换成了事件 %s；'
                    '而事件 %s 在本库里读不出来：读不出来时不说链到此为止。'
                    % (event,successor,successor))
        if ended=='cycle':
            return ('这次复核产出的那个版本（事件 %s）后来也被换掉了，换成了事件 %s；'
                    '而从事件 %s 沿替换关系往前走，又回到了事件 %s 自己：库里这段替换关系成了环，'
                    '说不出哪个是现在的版本。' % (event,successor,successor,tail))
        if hops>0:
            return ('这次复核产出的那个版本（事件 %s）后来也被换掉了，换成了事件 %s；'
                    '它换成的那个（事件 %s）此后又被换掉 %d 次，现在的链尾是事件 %s：'
                    '这次复核的结论已不是当前版本，行里留着的仍是它当时说的。'
                    % (event,successor,successor,hops,tail))
        return ('这次复核产出的那个版本（事件 %s）后来也被换掉了，换成了事件 %s：这次复核的结论已不是当前版本，'
                '行里留着的仍是它当时说的。' % (event,state.get('replacement')))
    return ('这次复核产出的那个版本（事件 %s）至今没被换掉：这只说明它还在架，不说明它判得对。' % event)


def content_runs(text):
    """Maximal runs of letters/digits.

    `_` joins a run: `INPUT_NAME` is one 10-character token, not 5+4, because
    an identifier is one word. Everything else breaks a run, so `true` is 4,
    `"value": 0.15` is 5 and `,` is 0.
    """
    import unicodedata
    runs=[];current=0
    for char in text or '':
        if char=='_' or unicodedata.category(char)[0] in {'L','N'}:
            current+=1
        elif current:runs.append(current);current=0
    if current:runs.append(current)
    return runs


def longest_content_run(text):
    runs=content_runs(text);return max(runs) if runs else 0
KINDS={'descriptive','causal','decision','definition','question'}
ROLES={'evidence','assumption','value'}


PROPOSAL_FIELDS={'statement','kind','method','premises','assumptions','conditions','alternatives','falsifier','revises'}
# Optional: a machine-checkable predicate bound to the exact falsifier prose.
# Absent stays valid; the prose alone still means "a human must read this".
OPTIONAL_FIELDS={'falsifier_check'}
# r65: readings the review packet already carries about a proposal's own
# history. Until r65 they were produced and stored but read only by tests:
# the CLI listing showed the proposal and its dependency status, so 'scored
# and survived', 'refused' and 'attempted and parked' were invisible to
# whoever reads the listing. One name for both readers, no new field.
PACKET_SURFACE_KEYS=('bridge','bridge_checked_without_hit','bridge_refused','review_attempts')

def validate_proposal(p):
    if not isinstance(p,dict) or not PROPOSAL_FIELDS <= set(p) or set(p)-PROPOSAL_FIELDS-OPTIONAL_FIELDS:raise ValueError('invalid proposal fields')
    if p['kind'] not in KINDS or p['method'] not in METHODS:raise ValueError('invalid knowledge type')
    for key in ('statement','falsifier'):
        if not isinstance(p[key],str) or not p[key].strip() or len(p[key])>4000:raise ValueError('invalid proposition text')
    if 'falsifier_check' in p:
        from .falsifier import compile_check
        p['falsifier_check']=compile_check(p['falsifier_check'],p['falsifier'])
    for key in ('assumptions','conditions','alternatives'):
        if not isinstance(p[key],list) or len(p[key])>12 or any(not isinstance(x,str) or not x.strip() or len(x)>2000 for x in p[key]):raise ValueError('invalid proposition context')
    if not isinstance(p['premises'],list) or not 1<=len(p['premises'])<=12:raise ValueError('proposition needs quoted premises')
    for premise in p['premises']:
        if not isinstance(premise,dict) or set(premise)!={'event','quote','role'} or type(premise['event']) is not int or premise['role'] not in ROLES:raise ValueError('invalid premise')
        if not isinstance(premise['quote'],str) or not premise['quote'].strip() or len(premise['quote'])>4000:raise ValueError('invalid premise quote')
    if p['revises'] is not None and type(p['revises']) is not int:raise ValueError('invalid revision target')
    return p


def event_text(kind,payload):
    if kind=='user':return payload['text']
    if kind=='reflection':return payload['reflection']['answer']
    if kind=='knowledge_proposal':return payload['proposal']['statement']
    if kind=='inquiry_question':return payload['text']
    return json.dumps(payload,ensure_ascii=False,sort_keys=True)


def tool_observation_text(payload):
    observed=payload['result'] if payload.get('status')=='executed' and 'result' in payload else {key:payload[key] for key in ('status','error_kind') if key in payload}
    kind=payload.get('action',{}).get('kind')
    if payload.get('status')=='executed' and isinstance(observed,dict):
        observed={k:v for k,v in observed.items() if k not in {'basis','assumptions','assertion','domain'}}
        if kind=='map_inquiry':return ''
        if kind=='text_experiment':
            observed={k:v for k,v in observed.items() if k not in {'sources','probes','arms'}}
            observed['arms']=[{k:v for k,v in arm.items() if k in {'arm','status','phase','error_kind','characters','literal_counts','semantic_accuracy'}} for arm in payload['result'].get('arms',[])]
    return json.dumps(observed,ensure_ascii=False,sort_keys=True)


class Knowledge:
    def __init__(self,connection,*,initialize=True):self.db=connection;self.dependencies=DependencyIndex(connection,initialize=initialize)

    def source(self,event):
        row=self.db.execute('SELECT run,kind,payload,at FROM inquiry_events WHERE seq=?',(event,)).fetchone()
        if row is None:raise ValueError('unknown knowledge source')
        run,kind,payload,at=row;payload=json.loads(payload)
        # `at` is when the record was written. Without it a reviewer cannot tell a
        # receipt observed last week from one observed a minute ago; the timestamp
        # otherwise survived only in a SQL column no review path reads.
        source={'event':event,'at':at,'kind':kind,'text':event_text(kind,payload),'run':run,'dependency_status':self.dependencies.status(event)}
        if kind=='knowledge_proposal':
            source['proposal']=payload['proposal']
            source['epistemic_status']='model_proposal_not_certified'
            if source['dependency_status']['state']=='needs_review':source['review_context']=self.review_context(event,source['dependency_status'])
        elif kind=='user':source['epistemic_status']='user_report_not_independently_verified'
        elif kind=='reflection':source['epistemic_status']='model_interpretation_not_certified'
        elif kind=='epistemic_check':source['epistemic_status']='model_critique_not_truth_verdict'
        elif kind in {'inquiry_question','question_parent','question_evidence'}:source['epistemic_status']='agent_organization_not_truth_verdict'
        elif kind=='tool_result':
            source['epistemic_status']='executed_tool_result_with_model_limits' if payload.get('status')=='executed' else 'tool_failure_not_positive_evidence'
            source['evidence_region']='computed_observation_fields_only; action_prediction_basis_assumptions_and_generated_text_are_context_only'
            planning=[row[0] for row in self.db.execute("SELECT premise FROM inquiry_dependencies WHERE conclusion=? AND relation='execution_context' ORDER BY premise",(event,))]
            if planning:
                source['execution_context_events']=planning
                source['observation_scope']='fixed_serialized_inputs; planning_provenance_is_not_applicability_proof'
        return source

    def observed_tool_text(self,event):
        row=self.db.execute("SELECT payload FROM inquiry_events WHERE seq=? AND kind='tool_result'",(event,)).fetchone()
        if row is None:raise ValueError('not a tool result')
        return tool_observation_text(json.loads(row[0]))

    def check(self,proposal,allowed_events,*,synthetic=False):
        """Check every anchor before a write. A valid quote still does not prove entailment."""
        validate_proposal(proposal)
        allowed=set(allowed_events)
        for premise in proposal['premises']:
            if premise['event'] not in allowed:raise ValueError('unseen premise')
            if isinstance(allowed_events,dict) and premise['quote'] not in allowed_events[premise['event']]:raise ValueError('premise quote not displayed')
            source=self.source(premise['event'])
            if premise['quote'] not in source['text']:raise ValueError('premise quote mismatch')
            if source['kind'] not in CITABLE_KINDS:raise ValueError('invalid source kind')
            if source['kind']=='reflection' and premise['role']!='assumption':raise ValueError('model interpretation requires assumption role')
            if source['kind']=='tool_result' and premise['role']=='evidence' and premise['quote'] not in self.observed_tool_text(premise['event']):raise ValueError('tool plan is not an observation')
            if source['dependency_status']['state']=='superseded':raise ValueError('superseded premise')
            if not synthetic and self.dependencies._synthetic(premise['event']):raise ValueError('synthetic premise')
            # Last, so a more specific refusal ('tool plan is not an observation',
            # 'invalid source kind') is not masked by a generic one. This lives on
            # the gate rather than in validate_proposal: a batch whose shape is
            # fine but whose citation is a comma is rejected per proposal into
            # `knowledge_rejected`, not sent back whole.
            if not citeable_quote(premise['quote']):raise ValueError('premise quote has no %d-character content run' % MIN_QUOTE_RUN)
        old=proposal['revises']
        if old is not None:
            if old not in allowed or self.source(old)['kind']!='knowledge_proposal':raise ValueError('unseen revision target')
            if self.dependencies.status(old)['state']=='superseded':raise ValueError('revision target already replaced')
            if self.dependencies._synthetic(old) is not synthetic:raise ValueError('revision identity mismatch')
            if any(x['event']==old or self.dependencies.depends_on(x['event'],old,include_execution_context=False) for x in proposal['premises']):raise ValueError('replacement depends on old proposition')

    def accept(self,run,proposal,allowed_events,*,synthetic=False):
        validate_proposal(proposal)
        # Exact duplicate proposals within one run are idempotent. Do not count restatement as evidence.
        canonical=json.dumps(proposal,ensure_ascii=False,sort_keys=True)
        for seq,payload in self.db.execute("SELECT seq,payload FROM inquiry_events WHERE run=? AND kind='knowledge_proposal'",(run,)):
            if json.dumps(json.loads(payload)['proposal'],ensure_ascii=False,sort_keys=True)==canonical:
                if not {x['event'] for x in proposal['premises']} <= set(allowed_events):raise ValueError('unseen premise')
                for premise in proposal['premises']:
                    if premise['role']=='evidence' and self.source(premise['event'])['kind']=='tool_result' and premise['quote'] not in self.observed_tool_text(premise['event']):raise ValueError('tool plan is not an observation')
                return seq
        self.check(proposal,allowed_events,synthetic=synthetic)
        run_start=self.db.execute("SELECT seq FROM inquiry_events WHERE run=? AND kind='start' ORDER BY seq LIMIT 1",(run,)).fetchone()
        if run_start is None or self.dependencies._synthetic(run_start[0])!=synthetic:raise ValueError('run identity mismatch')
        # DependencyIndex methods commit their own transactions; perform the
        # validated inserts directly here as one transaction.
        with self.db:
            cursor=self.db.execute('INSERT INTO inquiry_events(run,kind,payload,at) VALUES(?,?,?,?)',(run,'knowledge_proposal',json.dumps({'proposal':proposal,'synthetic':synthetic,'epistemic_status':'model_proposal_not_certified'},ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
            event=cursor.lastrowid
            for premise in sorted({x['event'] for x in proposal['premises']}):
                self.db.execute("INSERT INTO inquiry_dependencies(conclusion,premise,relation) VALUES(?,?,'premise')",(event,premise))
            old=proposal['revises']
            if old is not None:
                self.db.execute('INSERT INTO inquiry_revisions VALUES(?,?,?)',(old,event,'显式知识提议修订；不是判真'))
                self.db.execute("INSERT OR IGNORE INTO inquiry_review_queue(event,cause) SELECT conclusion,? FROM inquiry_dependencies WHERE premise=? AND relation!='execution_context'",(old,old))
        return event

    def request_review(self,run,target,sources,reason,allowed_events,*,synthetic=False,comparison=None):
        """Record a review request or an explicit comparison of two source reads.

        For a comparison, sources is ordered: cited basis first, other read
        second. Only a conflict reopens review. Old callers remain unclassified.
        """
        if comparison is not None:
            return self._record_comparison(run,target,list(sources),reason,set(allowed_events),synthetic,comparison)
        sources=sorted(set(sources));allowed=set(allowed_events)
        if target not in allowed or self.source(target)['kind']!='knowledge_proposal':raise ValueError('unseen review target')
        if self.dependencies.status(target)['state']=='superseded':raise ValueError('superseded review target')
        if not 1<=len(sources)<=4 or not isinstance(reason,str) or not reason.strip() or len(reason)>8000:raise ValueError('invalid evidence review request')
        start=self.db.execute("SELECT seq FROM inquiry_events WHERE run=? AND kind='start' ORDER BY seq LIMIT 1",(run,)).fetchone()
        if start is None or self.dependencies._synthetic(start[0])!=synthetic:raise ValueError('run identity mismatch')
        if self.dependencies._synthetic(target) is not synthetic:raise ValueError('review identity mismatch')
        for event in sources:
            if type(event) is not int or event not in allowed or event<=target:raise ValueError('review evidence must be shown and newer')
            source=self.source(event)
            if source['kind'] not in {'user','tool_result','knowledge_proposal'} or source['dependency_status']['state']!='current_interpretation':raise ValueError('review evidence is not a current source')
            if not synthetic and self.dependencies._synthetic(event):raise ValueError('synthetic review evidence')
            if self.dependencies.depends_on(event,target,include_execution_context=False):raise ValueError('review evidence is an echo of target')
        new=[event for event in sources if not self.db.execute('SELECT 1 FROM inquiry_review_queue WHERE event=? AND cause=?',(target,event)).fetchone()]
        if not new:return {'status':'unchanged','target':target}
        with self.db:
            payload={'target':target,'sources':new,'reason':reason,'synthetic':synthetic,'epistemic_status':'agent_review_request_not_truth_verdict'}
            notice=self.db.execute('INSERT INTO inquiry_events(run,kind,payload,at) VALUES(?,?,?,?)',(run,'review_evidence_notice',json.dumps(payload,ensure_ascii=False),datetime.now(timezone.utc).isoformat())).lastrowid
            for event in new:self.db.execute('INSERT OR IGNORE INTO inquiry_review_queue(event,cause) VALUES(?,?)',(target,event))
        return {'status':'requested','target':target,'notice_event':notice,'new_evidence_events':new}

    def _record_comparison(self, run, target, events, reason, allowed, synthetic, relation):
        from .independence_gap import evidence_events, read_receipts
        from .stories import run_index

        if (relation not in ('supports_independently', 'conflicts') or len(events) != 2
                or type(target) is not int or any(type(event) is not int for event in events)
                or events[0] == events[1] or not {target, *events} <= allowed
                or not isinstance(reason, str) or not reason.strip() or len(reason) > 8000):
            raise ValueError('invalid source comparison; show the proposal and two exact source events')
        runs = run_index(self.db)
        identity = runs.get(run)
        if identity is None or identity['synthetic'] is not synthetic:
            raise ValueError('run identity mismatch')

        def ledger(event, kind):
            row = self.db.execute('SELECT run,kind,payload FROM inquiry_events WHERE seq=?', (event,)).fetchone()
            owner = runs.get(row[0]) if row else None
            if (owner is None or owner['story'] != identity['story'] or owner['synthetic'] is not synthetic
                    or row[1] != kind):
                raise ValueError('comparison target and reads must be in the same story and identity')
            return {'event': event, 'kind': kind, 'payload': json.loads(row[2])}

        data = ledger(target, 'knowledge_proposal')['payload']
        if data.get('synthetic') is not synthetic or self.dependencies.status(target)['state'] == 'superseded':
            raise ValueError('comparison requires the current proposal version')
        first, second = events
        cited = evidence_events(data['proposal'])
        if first not in cited or (second not in cited and (relation != 'conflicts' or second <= target)):
            raise ValueError('comparison requires cited reads or newer counter-evidence')
        reads = read_receipts([ledger(event, 'tool_result') for event in events])
        for event in events:
            if (reads.get(event, {}).get('state') != 'visible_body'
                    or self.dependencies.status(event)['state'] != 'current_interpretation'
                    or self.dependencies._synthetic(event) is not synthetic
                    or self.dependencies.depends_on(event,target,include_execution_context=False)):
                raise ValueError('comparison requires executed, current source bodies that are not echoes')
        if relation == 'supports_independently' and reads[first]['key'] == reads[second]['key']:
            raise ValueError('same source URL is not independent material')

        comparison = {'relation': relation, 'events': events}
        # Reuse review requests even when a previous unclassified request has
        # already queued the same cause. The polarity is new; the cause is not.
        for seq, raw in self.db.execute("SELECT seq,payload FROM inquiry_events WHERE kind='review_evidence_notice'"):
            prior = json.loads(raw)
            if isinstance(prior, dict) and prior.get('target') == target and prior.get('comparison') == comparison and prior.get('reason') == reason:
                return {'status':'unchanged','target':target,'notice_event':seq}
        causes = [second] if relation == 'conflicts' else []
        payload = {'target':target,'sources':causes,'comparison':comparison,'reason':reason,
                   'synthetic':synthetic,'epistemic_status':'recorded_source_comparison_not_truth_verdict'}
        with self.db:
            notice = self.db.execute('INSERT INTO inquiry_events(run,kind,payload,at) VALUES(?,?,?,?)',
                (run,'review_evidence_notice',json.dumps(payload,ensure_ascii=False),datetime.now(timezone.utc).isoformat())).lastrowid
            for event in causes:
                self.db.execute('INSERT OR IGNORE INTO inquiry_review_queue(event,cause) VALUES(?,?)',(target,event))
        return {'status':'requested' if causes else 'recorded','target':target,'notice_event':notice,
                'comparison':comparison}

    def review_context(self,event,status):
        """Bounded read-time reasons, separate from the unchanged claim text."""
        causes=sorted(set(status.get('causes',[])),reverse=True)
        def excerpt(seq):
            row=self.db.execute('SELECT run,kind,payload,at FROM inquiry_events WHERE seq=?',(seq,)).fetchone()
            if row is None:return {'event':seq,'kind':'unknown','excerpt':'','at':None}
            run,kind,payload,at=row;payload=json.loads(payload)
            text=tool_observation_text(payload) if kind=='tool_result' else event_text(kind,payload)
            return {'event':seq,'run':run,'kind':kind,'at':at,'excerpt':text[:800],'excerpt_truncated':len(text)>800,
                'epistemic_status':('executed_tool_result_with_model_limits' if payload.get('status')=='executed' else 'tool_failure_not_positive_evidence') if kind=='tool_result' else
                    {'user':'user_report_not_independently_verified','knowledge_proposal':'model_proposal_not_certified','reflection':'model_interpretation_not_certified','epistemic_check':'model_critique_not_truth_verdict'}.get(kind,'record_not_truth_certificate')}
        items=[]
        for cause in causes[:4]:
            item=excerpt(cause)
            revision=self.db.execute('SELECT new_event,reason FROM inquiry_revisions WHERE old_event=?',(cause,)).fetchone()
            if revision:item.update(replacement=excerpt(revision[0]),change_reason=revision[1][:600],change_reason_truncated=len(revision[1])>600)
            items.append(item)
        from itertools import islice
        def requests():
            for seq,run,payload in self.db.execute("SELECT seq,run,payload FROM inquiry_events WHERE kind='review_evidence_notice' ORDER BY seq DESC"):
                notice=json.loads(payload)
                if notice.get('sources'):yield seq,run,notice
        rows=list(islice(requests(),65))
        notices=[];matches=0
        shown={item['event'] for item in items}
        for seq,run,notice in rows[:64]:
            if not shown.intersection(notice['sources']):continue
            if notice['target']!=event and not self.dependencies.depends_on(event,notice['target'],include_execution_context=False):continue
            matches+=1
            if len(notices)<3:notices.append({'event':seq,'run':run,'kind':'review_evidence_notice','target':notice['target'],
                'reason':notice['reason'][:600],'reason_truncated':len(notice['reason'])>600,
                **({'comparison':notice['comparison']} if 'comparison' in notice else {}),
                'epistemic_status':notice.get('epistemic_status','agent_review_request_not_truth_verdict')})
        return {'causes':items,'causes_omitted':max(0,len(causes)-len(items)),'requests':notices,
            'requests_omitted_in_scanned_window':matches-len(notices),'notice_scan_truncated':len(rows)>64,
            'scope':'Pending review signals, not a falsehood verdict. Excerpts may be reports or finite computations; assumptions and applicability still require review. Replacement is the first recorded successor, not necessarily the latest version.'}

    def pending_for_runs(self,runs,*,limit=4,max_characters=8000):
        """Small recovery previews, never an additional citation source."""
        runs=sorted(set(runs));items=[];used=0;more=False
        if not runs:return {'items':[],'more_pending':False,'preview_only':True}
        query="SELECT seq FROM inquiry_events WHERE kind='knowledge_proposal' AND run IN (%s) ORDER BY seq DESC" % ','.join('?' for _ in runs)
        for (event,) in self.db.execute(query,runs):
            state=self.dependencies.status(event)
            if state['state']!='needs_review':continue
            if len(items)>=limit:more=True;break
            source=self.source(event);context=source['review_context'];causes=[]
            for cause in context['causes'][:2]:
                item={**cause,'excerpt':cause['excerpt'][:300],'excerpt_truncated':cause.get('excerpt_truncated',False) or len(cause['excerpt'])>300}
                if 'replacement' in cause:
                    replacement=cause['replacement'];item['replacement']={**replacement,'excerpt':replacement['excerpt'][:300],'excerpt_truncated':replacement.get('excerpt_truncated',False) or len(replacement['excerpt'])>300}
                if 'change_reason' in cause:item.update(change_reason=cause['change_reason'][:300],change_reason_truncated=cause.get('change_reason_truncated',False) or len(cause['change_reason'])>300)
                causes.append(item)
            requests=[{**n,'reason':n['reason'][:300],'reason_truncated':n.get('reason_truncated',False) or len(n['reason'])>300} for n in context['requests'][:1]]
            preview={'event':event,'run':source['run'],'kind':'knowledge_proposal','text':source['text'][:600],'text_truncated':len(source['text'])>600,
                'epistemic_status':'model_proposal_not_certified','preview_only':True,
                'dependency_status':{**state,'causes':state['causes'][:4],'causes_omitted':max(0,len(state['causes'])-4)},
                'review_context':{**context,'causes':causes,'causes_omitted':context['causes_omitted']+len(context['causes'])-len(causes),
                    'requests':requests,'requests_omitted_in_scanned_window':context['requests_omitted_in_scanned_window']+len(context['requests'])-len(requests)}}
            size=len(json.dumps(preview,ensure_ascii=False))
            if used+size>max_characters:more=True;break
            items.append(preview);used+=size
        return {'items':items,'more_pending':more,'preview_only':True,
            'scope':'Pending knowledge created in these story runs, filtered before output bounds. Truncated previews are review warnings, not full propositions or citable evidence; inspect canonical sources before reuse.'}

    def proposals(self,*,synthetic=False,limit=100):
        rows=[]
        # r65: a full packet per row costs 2.3 ms, and retrieve_knowledge asks
        # for 500 rows on every agent turn. The keys only exist for proposals
        # some writer named, so resolve that set once per call.
        scored=_scored_events(self.db)
        for event,run,payload in self.db.execute("SELECT seq,run,payload FROM inquiry_events WHERE kind='knowledge_proposal' ORDER BY seq DESC LIMIT ?",(limit,)):
            data=json.loads(payload)
            if data['synthetic'] and not synthetic:continue
            status=self.dependencies.status(event)
            row={'event':event,'run':run,**data,'dependency_status':status,
                **({'review_context':self.review_context(event,status)} if status['state']=='needs_review' else {})}
            # r65: show what the packet already holds. Only keys the packet
            # actually carries are copied: an empty one would claim a reading
            # that does not exist, and a default would make 'never scored' look
            # like a reading. Read-only; nothing is written and no state moves.
            if event in scored:
                # r98: one premise event absent from this library used to abort
                # the whole listing right here (`error: unknown knowledge
                # source`, exit 2, empty stdout), so a single damaged reference
                # hid every other proposal and every recorded basis with it. The
                # packet cannot be rebuilt -- that is a fact about the packet,
                # not a verdict on the proposal -- and the attempts are still
                # read, because they are what records 'this review stood on X,
                # and X is no longer here'.
                try:
                    packet=self.review_packet(event)
                except ValueError:
                    missing=_unreadable_premises(
                        self.db,data['proposal'],
                        (status.get('causes') or []) if isinstance(status,dict) else ())
                    row['packet_unreadable']=(
                        '这个包今天重建不出来：%s在本库里找不到。所以这个包的内容和记下的复核摘要都没比过；'
                        '这不是在说这个说法错了，也不是在说这些复核没做过。' % _name_events(missing))
                    attempts=self.review_attempts(event,None)
                    if attempts:row['review_attempts']=attempts
                else:
                    for key in PACKET_SURFACE_KEYS:
                        if packet.get(key) is not None:row[key]=packet[key]
            rows.append(row)
        return rows

    def review_packet(self,event):
        source=self.source(event)
        if source['kind']!='knowledge_proposal':raise ValueError('only knowledge proposals can be rechecked')
        proposal=json.loads(self.db.execute('SELECT payload FROM inquiry_events WHERE seq=?',(event,)).fetchone()[0])['proposal']
        sources={x['event']:self.source(x['event']) for x in proposal['premises']}
        # Include latest replacements of every changed ancestor, not just the root's old wording.
        roots=self.dependencies.status(event).get('causes',[])
        for root in roots:
            seen=set()
            while root not in seen:
                seen.add(root);sources[root]=self.source(root)
                state=sources[root]['dependency_status']
                if state['state']!='superseded':break
                root=state['replacement']
        # Inspect the actual basis of model proposals rather than reviewing a
        # chain of model assertions as if it were independent evidence.
        queue=list(sources)
        expansion_truncated=False
        while queue:
            item=sources[queue.pop(0)]
            if item['kind']!='knowledge_proposal':continue
            for premise in item['proposal']['premises']:
                key=premise['event']
                if key in sources:continue
                if len(sources)>=32:expansion_truncated=True;continue
                sources[key]=self.source(key);queue.append(key)
        packet={'target':event,'proposal':proposal,'dependency_status':source['dependency_status'],'sources':list(sources.values()),'source_expansion_truncated':expansion_truncated,'truth':'not_certified'}
        from .anchors import anchor_catalog,CONTRACT
        packet['citation_contract']=CONTRACT
        packet['anchors']=anchor_catalog(self,packet['sources'],exclude_events=(event,))
        # The reviewer receives a packet, not the event log. A hit is reachable
        # from that packet only as one of at most four causes, and the hit payload
        # is not a citable source, so 'why is this pending' and 'what grid was it
        # scored on' could only be believed. Carry the bridge's own readings here
        # for every proposal a hit already landed on. Proposals that never crossed
        # the bridge get no key at all: adding an empty one would change every
        # stored packet digest and silently re-open 151 recorded review attempts.
        bridge=None
        for seq,payload in self.db.execute("SELECT seq,payload FROM inquiry_events WHERE kind='falsifier_hit' ORDER BY seq DESC"):
            data=json.loads(payload)
            if data.get('proposal')!=event:continue
            bridge={'hit_event':seq,'receipt':data.get('receipt'),'receipt_at':data.get('receipt_at'),
                    'predicate':data.get('predicate'),'evaluated':data.get('evaluated'),'hits':data.get('hits'),
                    'derived_compared':data.get('derived_compared'),'domain':data.get('domain'),
                    'epistemic_status':'finite_computation_under_stated_model_not_truth_verdict'}
            # r48 narrowed what `hits` counts, and rows written before it keep the
            # old meaning. The reviewer must be able to tell which definition
            # produced the number in front of them -- but adding these keys
            # unconditionally would change the packet digest of every proposal
            # already bridged, re-opening recorded review attempts. So they are
            # added only when the stored row actually carries them.
            if data.get('criteria_version'):
                bridge['hit_definition']=data.get('hit_definition')
                bridge['criteria_version']=data['criteria_version']
            # r62: only rows written after the gate existed carry this. Adding it
            # unconditionally would change the digest of every already-bridged
            # packet and silently re-open recorded review attempts.
            if 'receipt_passed' in data:
                bridge['receipt_passed']=data.get('receipt_passed')
            break
        if bridge is not None:packet['bridge']=bridge
        # 'Enumerated and survived' and 'never enumerated' used to produce the
        # same packet: a not_hit outcome is stored inside falsifier_bridge_checked,
        # which no reader touches, so a candidate that had actually been scored on
        # the receipt's grid looked exactly like one that never was. Record the
        # miss as well. The name says 'without_hit' rather than 'passed' and the
        # payload carries no verdict boolean, only how many points were computed:
        # surviving enumeration narrows nothing, and must not read as support.
        checked_without_hit=None
        for seq,raw in self.db.execute("SELECT seq,payload FROM inquiry_events WHERE kind='falsifier_bridge_checked' ORDER BY seq DESC"):
            data=json.loads(raw)
            match=next((o for o in data.get('outcomes') or [] if o.get('proposal')==event and o.get('status')=='not_hit'),None)
            if match is None:continue
            row=self.db.execute('SELECT at FROM inquiry_events WHERE seq=?',(data.get('receipt'),)).fetchone()
            checked_without_hit={'evaluated':match.get('evaluated'),'receipt':data.get('receipt'),
                    'receipt_at':row[0] if row else None,
                    'epistemic_status':'finite_computation_under_stated_model_not_truth_verdict'}
            break
        if checked_without_hit is not None:packet['bridge_checked_without_hit']=checked_without_hit
        # r62: the bridge can also refuse a candidate -- its declared grid does
        # not match the receipt, or the receipt's own assertion never held so the
        # hit carries no discrimination. Without this key a refused candidate and
        # a candidate that never crossed the bridge produced the same packet, so
        # 'the bridge computed this and rejected it' was invisible to the reader
        # who is supposed to judge it (r60). Named for the event, not a verdict:
        # no hits/passed/verified field, and the status is untouched -- a refusal
        # neither reopens nor closes review work.
        refused=None
        for seq,raw in self.db.execute("SELECT seq,payload FROM inquiry_events WHERE kind='falsifier_bridge_checked' ORDER BY seq DESC"):
            data=json.loads(raw)
            # The newest outcome for this proposal decides. Scanning for the first
            # *refused* instead would let a refusal superseded by a later hit or
            # miss stay on the packet as if it were the current reading.
            match=next((o for o in data.get('outcomes') or [] if o.get('proposal')==event),None)
            if match is None:continue
            if match.get('status')!='refused':break
            row=self.db.execute('SELECT at FROM inquiry_events WHERE seq=?',(data.get('receipt'),)).fetchone()
            refused={'receipt':data.get('receipt'),'receipt_at':row[0] if row else None,
                    'reason':match.get('reason'),'detail':match.get('detail'),
                    'epistemic_status':'finite_computation_under_stated_model_not_truth_verdict'}
            break
        if refused is not None:packet['bridge_refused']=refused
        # r58 A: a hit names the proposal id that was scored. A review that
        # replaces that proposal mints a new id which receipt_hits never scores in
        # that run (falsifier.py scans `WHERE run=?`), so the new packet showed no
        # bridge at all and its reader could not tell 'scored and survived' from
        # 'never scored' -- the same shape r37/r60/r62 fixed for the old id. Carry
        # the old reading forward by one revision step and say where it came from.
        # Nothing is re-scored, no state moves and no verdict boolean is added:
        # `inherited_from` is the whole difference between this and a hit on self.
        if bridge is None:
            previous=self.db.execute('SELECT old_event FROM inquiry_revisions WHERE new_event=?',(event,)).fetchone()
            if previous is not None:
                for seq,raw in self.db.execute("SELECT seq,payload FROM inquiry_events WHERE kind='falsifier_hit' ORDER BY seq DESC"):
                    data=json.loads(raw)
                    if data.get('proposal')!=previous[0]:continue
                    bridge={'hit_event':seq,'inherited_from':previous[0],
                            'receipt':data.get('receipt'),'receipt_at':data.get('receipt_at'),
                            'predicate':data.get('predicate'),'evaluated':data.get('evaluated'),'hits':data.get('hits'),
                            'derived_compared':data.get('derived_compared'),'domain':data.get('domain'),
                            'epistemic_status':'finite_computation_under_stated_model_not_truth_verdict',
                            'scope':"prior proposal's readings; this proposal was never scored"}
                    if data.get('criteria_version'):
                        bridge['hit_definition']=data.get('hit_definition')
                        bridge['criteria_version']=data['criteria_version']
                    if 'receipt_passed' in data:
                        bridge['receipt_passed']=data.get('receipt_passed')
                    if bridge is not None and 'bridge' not in packet:packet['bridge']=bridge
                    break
        # The digest says which content was reviewed, not when. Timestamps are
        # per-event immutable, so leaving them out of the hash loses no identity
        # while keeping the digest comparable with attempts recorded before the
        # sources carried `at` at all.
        packet['sha256']=_content_digest(packet)
        # r61/r63: `review_failure` and `knowledge_review` rows are what suppress a
        # packet from being offered again (`review_candidates` keeps an `attempted`
        # set of packet digests). That suppression was the only trace of the
        # attempt, so a parked proposal and one never examined produced the same
        # packet. Record the attempts keyed by *this* digest: an attempt on other
        # content does not explain this exclusion, and showing it would put the key
        # on 2 more real packets (5 rather than 3). The key is digest-neutral
        # (anchors.DIGEST_NEUTRAL_KEYS): a record that changed the digest would
        # un-suppress the very packet it describes.
        digest=packet['sha256']
        attempts=self.review_attempts(event,digest)
        if attempts:packet['review_attempts']=attempts
        return packet

    def review_attempts(self,event,digest):
        """The stored reviews of one packet, read without rebuilding the packet.

        r98: this loop used to live inside `review_packet`, which aborts while
        building `sources` when a proposal names a premise event the library no
        longer holds. The listing called `review_packet` for every scored
        proposal, so one dangling reference took the whole `dojo knowledge` run
        down with `error: unknown knowledge source` (exit 2, empty stdout) -- and
        the sentence written for exactly that case, in `basis_source_state`,
        could never be printed because nothing ever got that far. Measured on a
        copy of the r97 run db with event 2 deleted: exit 2, and
        `basis_source_state` returned the right sentence when called directly.

        Reading the attempts needs only the digest to compare against, not the
        packet's contents. `digest=None` means the packet could not be rebuilt
        today: that is its own state, not 'same as today' and not 'written under
        another rule', because neither comparison happened.

        `review_packet` keeps refusing. A reviewer that cannot read the basis
        must not review it; only the listing degrades, and it says why.
        """
        attempts=[]
        for seq,kind,raw in self.db.execute("SELECT seq,kind,payload FROM inquiry_events WHERE kind IN ('knowledge_review','review_failure') ORDER BY seq"):
            data=json.loads(raw)
            if data.get('target')!=event:continue
            stored_digest=data.get('packet_sha256')
            # r87: a different digest used to mean 'skip', and skipping was silent.
            # Two readers then saw the same thing for two different situations:
            # 'never reviewed' and 'reviewed under a rule that has since changed'.
            # Measured: the packet rebuilt as of the review is byte-identical to
            # today's, so the drift is in the digest *rule*, not the material --
            # and r86/resuppress.py showed the consequence: offered again, with no
            # attempt shown. Now the attempt is listed either way; what differs is
            # the sentence beside it and whether the packet is offered again. Both
            # live on the attempt item, which `review_attempts` keeps digest-neutral
            # at any depth -- a top-level key would move every stored digest.
            # Unchanged text on purpose: `tests/test_digest_consumers.py` audits
            # this line as 'same-bytes' and the allowlist is edited deliberately,
            # never to accommodate a diff. When `digest` is None the branch below
            # returns before this value is read, so the comparison is never used
            # to stand in for a comparison that did not happen.
            matches=stored_digest==digest
            changed=_reopened_since(self.db,event,seq)
            row=self.db.execute('SELECT at FROM inquiry_events WHERE seq=?',(seq,)).fetchone()
            # `packet_sha256` keeps its meaning: the digest stored on that row.
            # The state beside it is a string, not a boolean, on purpose: attempt
            # items carry no verdict boolean anywhere (a test pins that), because
            # `digest_matches: False` reads as 'this review failed' rather than
            # 'the rule changed'. These name which digest, and what came after.
            # r98: three states, not two. `digest is None` means today's packet
            # could not be rebuilt at all, so no comparison happened -- printing
            # that as 'the material differs' would invent a difference.
            if digest is None:
                item={'kind':kind,'at':row[0] if row else None,'packet_sha256':stored_digest,
                      'digest':'packet_unreadable_today'}
                item['reading']=('这个包今天重建不出来，所以这次复核记下的摘要（%s）没跟今天比过：'
                                 '没比成不等于材料变了，也不等于这次复核没通过。'
                                 % (stored_digest or '<无>')[:12])
                item['reopened_since']='yes' if changed else 'no'
            else:
                item={'kind':kind,'at':row[0] if row else None,'packet_sha256':stored_digest,
                      'digest':'same_as_today' if matches else 'written_under_another_rule'}
                if not matches:
                    item['reading']=('这次复核记录在一个不同的内容摘要下（%s，今天算得 %s）：摘要不同不等于没复核过，'
                                     '也不说明材料变了。%s' % ((stored_digest or '<无>')[:12],digest[:12],
                                     '不过这次复核之后这个包又有了新的复核工作，所以它会被再提出来一次。' if changed else
                                     '这次复核之后这个包没有新的复核工作，所以不会再提出来。'))
                    item['reopened_since']='yes' if changed else 'no'
            # The event kind and the failure kind are different things: a
            # `review_failure` row's `kind` field is *why* it failed.
            if kind=='review_failure':item['failure']=data.get('kind')
            if kind=='review_failure':item['failure']=data.get('kind')
            else:item['disposition']=data.get('disposition')
            # r95: `disposition` says what the review decided. It does not say
            # whether the version the review produced is still the current one.
            # 22/146 `knowledge_review` rows (and 15/104 `question_review` rows)
            # name an outcome event that is itself in `inquiry_revisions.old_event`,
            # and the listing printed `retain` for them in the present tense. Read
            # from the ledger now; the stored row keeps its bytes, and the key is a
            # sibling under `review_attempts`, which `anchors` strips before hashing,
            # so no stored packet digest moves.
            item['replacement_event']=data.get('replacement_event')
            item['outcome_state_now']=outcome_source_state(self,item,kind)
            # r86: rows written from r86 on carry the basis themselves. Copied
            # only when the stored row has it -- a default would make a review
            # recorded before r86 claim a basis it never wrote. The digest does
            # not see any of this (`review_attempts` is digest-neutral), so
            # adding it cannot re-open a recorded attempt.
            #
            # r89: the `if` used to have no `else`, so a row without a basis
            # looked exactly like a row whose basis was never worth recording --
            # and the row still carries `at`, the time the *review* happened,
            # which reads like an answer to 'when was this based on'. A string,
            # not a boolean (a `basis_missing: False` would read as a verdict),
            # and it says what is in the row, not that the review was wrong: an
            # older review may well have needed no basis at all.
            stored=data.get('premise_events')
            if kind=='knowledge_review' and isinstance(stored,list) and stored:
                # r94: the stored `reading` is the sentence from the day the review
                # ran, and its `dependency_state` is a snapshot that cannot age. A
                # copy of a real db was measured where a basis was replaced after
                # the row was written and the listing stayed byte-identical to the
                # arm where nothing moved. Recomputed here, never written back, and
                # kept as a separate sentence beside the stored one rather than
                # overwriting it: 'what it was then' and 'what it is now' are two
                # facts, and folding them into one sentence loses the difference
                # that makes the row auditable.
                item['premise_events']=stored
                # Sibling key, not an edit of the stored list: a reader comparing
                # `premise_events` with the row on disk must still find them
                # identical (a test pins exactly that), and 'what it was then' is
                # already in that list. This says what the same citations are now.
                item['basis_state_now']=[basis_source_state(self,x) for x in stored]
                item['basis_readings']=data.get('basis_readings') or [x.get('reading') for x in stored]
                # r97: a row can name a basis and still not let a reader check it --
                # a quote that locates nothing, a field missing from an entry, fewer
                # readings than entries. Set only when a gap exists, so a complete
                # row keeps exactly the keys it had.
                gaps=basis_gaps(stored,item['basis_readings'])
                if gaps:item['basis_incomplete']=gaps
                item['basis_readings']=data.get('basis_readings') or [x.get('reading') for x in stored]
            elif kind=='knowledge_review':
                # Empty list counts here too: a row that names a basis list but
                # lists nothing has not recorded a basis, and must not read as
                # though it had.
                item['basis_missing']=('这条复核记录里没有依据条目：没有记录它依据了哪几句，'
                                       '也没有那些句子的时刻。')
            else:
                item['basis_missing']=('这次复核没有完成，所以这行上没有记录它依据了哪几句。')
            attempts.append(item)
        return attempts

    def review_candidates(self,*,synthetic=False,limit=2,retry_failures=False,run=None,story=None):
        if type(limit) is not int or not 0<=limit<=1000:raise ValueError('invalid review candidate limit')
        if limit==0:return []
        kinds=('knowledge_review',) if retry_failures else ('knowledge_review','review_failure')
        # r87: this used to be a set of digests, and membership was the whole test.
        # A stored digest computed under an older rule therefore excluded nothing:
        # the packet was offered again with no attempt shown, so 'reviewed under a
        # different rule' and 'never reviewed' read the same. Group the attempt rows
        # by target once, keeping each row's sequence number: the decision below
        # needs to ask whether anything has changed this packet since that write.
        attempts_by_target={}
        for seq,payload in self.db.execute("SELECT seq,payload FROM inquiry_events WHERE kind IN (%s) ORDER BY seq" % ','.join('?' for _ in kinds),kinds):
            data=json.loads(payload)
            if data.get('target') is None:continue
            attempts_by_target.setdefault(data['target'],[]).append((seq,data.get('packet_sha256')))
        candidates=[]
        # A bounded follow-up must examine the target it just reopened before
        # spending its allowance on unrelated historical pending proposals.
        # Keep historical ordering otherwise; a new run does not inherit this
        # scheduling preference, and attempted packets remain suppressed.
        priority={}
        if run is not None:
            for seq,payload in self.db.execute("SELECT seq,payload FROM inquiry_events WHERE run=? AND kind='review_evidence_notice' ORDER BY seq",(run,)):
                notice=json.loads(payload)
                if notice.get('sources'):priority.setdefault(notice['target'],seq)
        # Reading may include ordinary knowledge in a synthetic sandbox, but a
        # mutation worker must only change targets of its own identity.
        from .stories import run_index
        scope={r for r,item in run_index(self.db).items() if item['synthetic'] is synthetic and (story is None or item['story']==story)}
        targets=set()
        if story is not None:
            for origin,payload in self.db.execute("SELECT run,payload FROM inquiry_events WHERE kind='review_evidence_notice'"):
                if origin in scope:
                    notice=json.loads(payload)
                    target=notice['target']
                    if notice.get('sources') and self.dependencies._synthetic(target) is synthetic:targets.add(target)
        def ordered():
            # Explicit current work must remain reachable beyond a recent-pool
            # cap. Other candidates keep newest-first ordering, but the result
            # limit is applied after identity, story, status and retry checks.
            for target in priority:
                row=self.db.execute("SELECT seq,run,payload FROM inquiry_events WHERE seq=? AND kind='knowledge_proposal'",(target,)).fetchone()
                if row:yield row
            yield from self.db.execute("SELECT seq,run,payload FROM inquiry_events WHERE kind='knowledge_proposal' ORDER BY seq DESC")
        seen=set()
        for event,origin,payload in ordered():
            if event in seen:continue
            seen.add(event)
            if origin not in scope and event not in targets:continue
            if json.loads(payload)['synthetic'] is not synthetic:continue
            if self.dependencies.status(event)['state']!='needs_review':continue
            packet=self.review_packet(event)
            # Suppress only when an attempt on this target is still about this
            # content: same digest, or a different digest with nothing written since
            # that could have moved the packet. A drifted digest plus later writes is
            # real new work and must be offered -- the attempt is still listed.
            still_attempted=False
            for seq,stored_digest in attempts_by_target.get(event,()):
                if stored_digest==packet['sha256'] or not _reopened_since(self.db,event,seq):
                    still_attempted=True;break
            if not still_attempted:candidates.append(packet)
            if len(candidates)>=limit:break
        return candidates
