"""Story identity is derived from immutable start events, not a parallel diary."""
import json
from pathlib import Path
import sqlite3

REVIEW_ORIGIN_GUIDANCE='\n前一条review_source_attributions消息仅为程序计算的出处标签，不是新证据。review_run_story是复核运行的归属，不代表当前有一位用户提供了全部材料。other_story或unknown的报告须称来源故事/案例报告，不写成当前会话用户经历；命题在本故事生成，也不改变其引用报告的来源。same_story报告同样未经独立验证。出处标签不能支持命题真假，仍以最后一条规范packet的anchors选择引文。'


def review_origin_view(q,packet):
    """A body-free attribution sidecar; canonical review/hash stays intact."""
    def meta(source):
        item={k:source[k] for k in ('event','run','kind','origin_story','story_scope','attribution') if k in source}
        premises=source.get('proposal',{}).get('premises',[])
        if premises:item['premise_sources']=[{'event':p['event'],'kind':p.get('source_kind'),**p.get('source_origin',{})} for p in premises]
        context=source.get('review_context',{})
        signals=[]
        for cause in context.get('causes',[]):
            signals.append({**meta(cause),'role':'review_cause'})
            if isinstance(cause.get('replacement'),dict):signals.append({**meta(cause['replacement']),'role':'cause_successor'})
        signals.extend({**meta(request),'role':'agent_review_request'} for request in context.get('requests',[]))
        if signals:item['review_signals']=signals
        return item
    target=q.scoped_sources([q.knowledge.source(packet['target'])])[0]
    return {'review_run_story':q.story,'target':meta(target),
        'sources':[meta(source) for source in q.scoped_sources(packet['sources'])],
        'scope':'Program-derived origins only, not new testimony or truth evidence. The review run story is bookkeeping, not ownership of every quoted report. The canonical packet and citation contract are unchanged.'}

def intent_coverage(user_events,snapshot_event):
    pending=[event for event in user_events if snapshot_event is None or event>snapshot_event]
    return {'intent_snapshot_event':snapshot_event,
        'intent_snapshot_state':'absent' if snapshot_event is None else ('new_user_input_pending' if pending else 'no_later_user_input'),
        'user_events_after_intent':pending[-12:],'user_events_after_intent_omitted':max(0,len(pending)-12)}


def run_index(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inquiry_events'").fetchone():return {}
    runs={}
    for seq,run,payload,at in db.execute("SELECT seq,run,payload,at FROM inquiry_events WHERE kind='start' ORDER BY seq"):
        if run in runs:continue
        value=json.loads(payload)
        runs[run]={'run':run,'story':value.get('story',run),'synthetic':value.get('synthetic',True), 'start_event':seq,'at':at}
    return runs


def source_view(source,story,runs,*,premise_sources=None):
    """Presentation-only origin labels; canonical source/hash stays unchanged."""
    origin=runs.get(source.get('run'),{}).get('story')
    scope='same_story' if origin==story else ('other_story' if origin is not None else 'unknown')
    view={'origin_story':origin,'story_scope':scope,**source}
    if source.get('kind')=='user':
        view['attribution']='reported_in_current_story' if scope=='same_story' else 'historical_report_not_current_user_testimony'
    if source.get('kind')=='knowledge_proposal' and isinstance(source.get('proposal'),dict):
        # A proposal's creation story does not own the reports it quotes. Label
        # each embedded premise, rather than relying on a distant catalog entry.
        # Only presentation copies gain fields; the stored contract stays exact.
        premises=[]
        for premise in source['proposal'].get('premises',[]):
            meta=(premise_sources or {}).get(premise['event'],{})
            presented=source_view(meta,story,runs)
            identity={key:presented[key] for key in ('origin_story','story_scope','attribution') if key in presented}
            premises.append({'source_kind':meta.get('kind'),'source_origin':identity,**premise})
        view['proposal']={**source['proposal'],'premises':premises}
        view['proposal_view']='Presentation includes premise source origins; creation here does not make quoted reports current-user testimony. Canonical proposal is unchanged.'
    if isinstance(source.get('review_context'),dict):
        context=source['review_context'];causes=[]
        for cause in context.get('causes',[]):
            item=source_view(cause,story,runs)
            if isinstance(cause.get('replacement'),dict):item['replacement']=source_view(cause['replacement'],story,runs)
            causes.append(item)
        view['review_context']={**context,'causes':causes,'requests':[source_view(item,story,runs) for item in context.get('requests',[])]}
    return view


def _resume_tool_receipts(tools):
    """Prioritize nearby source bodies, not inferred version relationships."""
    recent=tools[-12:][::-1]

    def is_source(event):
        payload=event['payload']
        action=payload.get('action')
        result=payload.get('result')
        if not (isinstance(action,dict) and action.get('kind')=='read_source'
                and payload.get('status')=='executed' and isinstance(result,dict)):
            return False
        url=action.get('url')
        text=result.get('text')
        return (isinstance(url,str) and url.startswith('https://') and url==result.get('url')
                and isinstance(text,str) and bool(text.strip()))

    reads=[]
    other=[]
    seen_bodies=set()
    for event in recent:
        action=event['payload'].get('action')
        if not (isinstance(action,dict) and action.get('kind')=='read_source'):
            if isinstance(action,dict):other.append(event)
            continue
        if not is_source(event):continue
        result=event['payload']['result']
        body=(result['url'],result['text'])
        if body in seen_bodies:continue
        seen_bodies.add(body)
        reads.append(event)
    selected={event['event'] for event in (reads+other)[:3]}
    return [event for event in recent if event['event'] in selected]


def describe(db,story,*,synthetic=False):
    plan,_=_describe(db,story,synthetic=synthetic,index=run_index(db))
    return plan


def _describe(db,story,*,synthetic,index):
    runs=[r for r in index.values() if r['story']==story]
    if not runs:raise ValueError('故事不存在；未开始新的探究')
    if any(r['synthetic'] is not synthetic for r in runs):raise ValueError('故事的合成/普通身份不匹配，不能跨身份续谈')
    scope={r['run'] for r in runs};events=[]
    for seq,run,kind,payload in db.execute("SELECT seq,run,kind,payload FROM inquiry_events WHERE kind IN ('user','tool_result','reflection','distillation','knowledge_proposal','epistemic_check') ORDER BY seq"):
        if run in scope:events.append({'event':seq,'run':run,'kind':kind,'payload':json.loads(payload)})
    users=[e for e in events if e['kind']=='user']
    tools=[e for e in events if e['kind']=='tool_result']
    all_replies=[e for e in events if e['kind']=='reflection' and e['payload']['reflection'].get('action') is None]
    # r102: two real libraries under `docs/evidence` store `delivered` rows whose
    # payload has no `reflection_event` (written by an older writer). Indexing it
    # raised a bare `KeyError` out of `stories`, so the whole listing died with a
    # traceback instead of naming the one row it could not read.
    delivered=set()
    for run,payload in db.execute("SELECT run,payload FROM inquiry_events WHERE kind='delivered'"):
        if run not in scope:continue
        try:value=json.loads(payload)
        except ValueError:continue
        if isinstance(value,dict) and value.get('reflection_event') is not None:
            delivered.add(value['reflection_event'])
    replies=[e for e in all_replies if e['event'] in delivered]
    all_opinions=[e for e in events if e['kind']=='epistemic_check' and e['payload'].get('issues')]
    opinions=[e for e in all_opinions if e['payload'].get('target') in delivered]
    intents=[e for e in events if e['kind']=='distillation' and e['payload'].get('intent') is not None]
    latest=intents[-1] if intents else None
    by_id={e['event']:e for e in events}
    candidates=[]
    def add(event):
        if event in by_id and event not in candidates:candidates.append(event)
    if users:add(users[0]['event'])
    if latest:
        for key in ('goals','motivations'):
            for item in latest['payload']['intent'][key]:
                origin=by_id.get(item['source_event'])
                if origin and origin['kind']=='user':add(origin['event'])
    for group in (users[-12:][::-1],opinions[-2:][::-1],_resume_tool_receipts(tools),replies[-2:][::-1]):
        for event in group:add(event['event'])
    return {'story':story,'synthetic':synthetic,'runs':runs,'candidate_events':candidates,
        **intent_coverage([e['event'] for e in users],latest['event'] if latest else None),
        'context_event_count':len(users)+len(tools)+len(all_replies)+len(all_opinions),'internal_replies_not_restored':len(all_replies)-len(replies),'internal_critiques_not_restored':len(all_opinions)-len(opinions),
        'latest_intent_snapshot':latest,'opening':users[0]['payload']['text'] if users else None},events


def prepare_resume(path,story,*,synthetic=False,with_source_comparison=False):
    """Validate before any writable connection, directory creation or model request."""
    if not isinstance(story,str) or not story.strip() or len(story)>128:raise ValueError('故事标识无效')
    path=Path(path)
    if not path.is_file():raise ValueError('故事数据库不存在；未创建文件')
    try:
        db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            db.execute('BEGIN')
            index = run_index(db)
            plan, events = _describe(db, story, synthetic=synthetic, index=index)
            if with_source_comparison:
                plan['source_comparison'] = _story_independence_gap(
                    db, story, index, [r['run'] for r in plan['runs']], events)
            return plan
        finally:db.close()
    except sqlite3.Error:raise ValueError('无法读取故事数据库') from None


def reading_source(source, story, index):
    from datetime import datetime
    source = dict(source)
    at = source.pop('at')
    status = 'missing'
    if at is not None and (not isinstance(at, str) or at.strip()):
        try:
            stamp = datetime.fromisoformat(at)
            status = 'recorded' if stamp.utcoffset() is not None else 'invalid'
        except (TypeError, ValueError, OverflowError):
            status = 'invalid'
    return {**source_view(source, story, index), 'recorded_at': at if status=='recorded' else None,
            'recorded_at_status': status}


def evidence_context(knowledge, sources, events):
    """Separate a recorded use as evidence from the relationship between bodies."""
    reads = {}
    for source in sources:
        if source['kind'] != 'tool_result':
            continue
        try:
            receipt = json.loads(source['text'])
        except ValueError:
            continue
        if not isinstance(receipt, dict):
            continue
        action, result = receipt.get('action'), receipt.get('result')
        if (receipt.get('status') == 'executed' and isinstance(action, dict)
                and action.get('kind') == 'read_source' and isinstance(result, dict)
                and isinstance(result.get('text'), str) and result.get('url') == action.get('url')):
            reads[source['event']] = (result['url'], result['text'])
    if not reads:
        return []
    uses = {event: [] for event in reads}
    # _describe already decoded only this story's readable runs, in seq order.
    # Reuse those rows instead of scanning the unindexed ledger a second time.
    for entry in reversed(events):
        if entry['kind'] != 'knowledge_proposal':
            continue
        event = entry['event']
        proposal = entry['payload']['proposal']
        premises = {p['event'] for p in proposal['premises'] if p['role'] == 'evidence'}
        for source_event in premises.intersection(reads):
            if len(uses[source_event]) < 3:
                uses[source_event].append({'proposal_event': event, 'statement': proposal['statement'],
                    'state': knowledge.dependencies.status(event)['state']})
    return [{'event': event, 'different_body_same_url': [other for other, (u, t) in reads.items()
                if other != event and u == url and t != text],
             'evidence_uses': uses[event]} for event, (url, text) in reads.items()]


def _record_time(at):
    """Same status contract as reading_source, reused for the takeover summary."""
    from datetime import datetime
    status = 'missing'
    if at is not None and (not isinstance(at, str) or at.strip()):
        try:
            stamp = datetime.fromisoformat(at)
            status = 'recorded' if stamp.utcoffset() is not None else 'invalid'
        except (TypeError, ValueError, OverflowError):
            status = 'invalid'
    return (at if status == 'recorded' else None), status


def _latest_record_time(db, runs):
    """The story's newest ledger row, including kinds this view does not read."""
    if not runs:
        return None, None, 'missing'
    placeholders = ','.join('?' for _ in runs)
    row = db.execute('SELECT seq,at FROM inquiry_events WHERE run IN (%s) ORDER BY seq DESC LIMIT 1' % placeholders,
                     tuple(runs)).fetchone()
    if row is None:
        return None, None, 'missing'
    at, status = _record_time(row[1])
    return row[0], at, status


def _search_listings(receipts, *, searches=12):
    return [entry for entry in receipts[-12:]
            if isinstance(entry['payload'].get('action'), dict)
            and entry['payload']['action'].get('kind') == 'search'
            and entry['payload'].get('status') == 'executed'
            and isinstance(entry['payload'].get('result'), dict)
            and isinstance(entry['payload']['result'].get('sources'), list)][-searches:]


def _source_url_key(url):
    from urllib.parse import urldefrag
    if isinstance(url, str) and url.startswith('https://'):
        try:
            return urldefrag(url)[0]
        except ValueError:
            pass
    return None


def _listed_sources(listings):
    for entry in reversed(listings):
        for row in entry['payload']['result']['sources']:
            if not isinstance(row, dict):
                continue
            url, title = row.get('url'), row.get('title')
            key = _source_url_key(url)
            if key and isinstance(title, str) and title.strip():
                yield key, {'title': title[:160], 'title_truncated': len(title) > 160,
                            'url': url, 'search_event': entry['event']}


def unopened_search_sources(events,*,cap=4,searches=12):
    """URLs listed by a search with no read_source receipt in this story."""
    receipts = [entry for entry in events if entry['kind'] == 'tool_result']
    seen = set()
    for entry in receipts:
        action = entry['payload'].get('action')
        if isinstance(action, dict) and action.get('kind') == 'read_source':
            key = _source_url_key(action.get('url'))
            if key:
                seen.add(key)
    listings = _search_listings(receipts, searches=searches)
    items = []
    for key, item in _listed_sources(listings):
        if key not in seen:
            seen.add(key)
            items.append(item)
    return items[:cap], max(0, len(items) - cap), len(listings)


def _source_failure_kind(error):
    import re
    return isinstance(error, str) and re.fullmatch(r'source_(?:connect|type|http_[1-5][0-9]{2})', error)


def _comparison_notices(db, runs):
    """Read only this story's explicit comparisons; legacy notices have no polarity."""
    placeholders = ','.join('?' for _ in runs)
    for seq, raw in db.execute("SELECT seq,payload FROM inquiry_events WHERE kind='review_evidence_notice' "
                               "AND run IN (%s) ORDER BY seq" % placeholders, tuple(runs)):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get('comparison'), dict):
            yield seq, data


def _comparison_target_status(db, story, index, successors, target):
    """Why `--comparison TARGET` has no row; four refusals that need different next steps."""
    if type(target) is not int:
        return {'target': target, 'state': 'invalid'}
    row = db.execute('SELECT run,kind FROM inquiry_events WHERE seq=?', (target,)).fetchone()
    if row is None:
        return {'target': target, 'state': 'absent'}
    owner = index.get(row[0], {}).get('story')
    if owner != story:
        return {'target': target, 'state': 'other_story', 'story': owner}
    if row[1] != 'knowledge_proposal':
        return {'target': target, 'state': 'not_a_proposal', 'kind': row[1]}
    if target in successors:
        return {'target': target, 'state': 'replaced', 'replacement_event': successors[target]}
    return {'target': target, 'state': 'no_comparison_record'}


def _comparison_refusal(status):
    """Name the specific next step; a replaced conclusion and a missing number differ."""
    target, state = status.get('target'), status.get('state')
    if state == 'replaced':
        return (f'事件 #{target} 的结论已被事件 #{status["replacement_event"]} 替代；'
                '比较记录只适用于被替代的旧版。当前版请用 stories STORY --comparison '
                f'{status["replacement_event"]} 查看。')
    if state == 'absent':
        return f'事件 #{target} 在本故事账本里不存在；没有可读的比较记录。'
    if state == 'other_story':
        return f'事件 #{target} 属于另一个故事；本故事内没有这条提议比较记录。'
    if state == 'not_a_proposal':
        return (f'事件 #{target} 是 {status.get("kind")} 记录，不是知识提议；'
                '--comparison 只查本故事内的知识提议。')
    return f'事件 #{target} 没有可见的当前提议比较记录。'
def _story_independence_gap(db, story, index, runs, events, *, target=None):
    """One ledger interpretation for the local view and the resume preview."""
    from .independence_gap import independence_gap

    def premise_lookup(event):
        if type(event) is not int:
            return {'exists': False}
        row = db.execute('SELECT run,kind FROM inquiry_events WHERE seq=?', (event,)).fetchone()
        if row is None:
            return {'exists': False}
        owner = index.get(row[0], {}).get('story')
        return {'exists': True, 'kind': row[1], 'same_story': owner == story, 'story': owner}

    successors = {}
    if any(e['kind'] == 'knowledge_proposal' for e in events) and db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='inquiry_revisions'").fetchone():
        successors = dict(db.execute('SELECT old_event,new_event FROM inquiry_revisions'))
    result = independence_gap(events, lookup=premise_lookup, revised=successors,
                              successors=successors, notices=_comparison_notices(db, runs), target=target)
    # #3230: an absent number and a replaced old conclusion used one sentence, yet
    # they lead to different next steps -- one has a successor to read, the other has
    # no record at all. Decide it here, where the ledger and the story index are open.
    if target is not None and not result['items']:
        result['target_status'] = _comparison_target_status(db, story, index, successors, target)
    return result


def resume_comparison_view(missing, restored_events, *, max_characters=8000):
    """Bound a non-citable preview; do not restore any extra bodies or anchors."""
    from .independence_gap import COMPARISON_DETAIL_LIMIT as COMPARISON_EVENT_LIMIT

    restored_events = set(restored_events)
    queue = [row['conclusion_event'] for row in missing['items']]
    hidden = missing.get('omitted_events_hidden', 0)
    preview = {'items': [], 'omitted': missing['conclusions_in_ledger'],
               'omitted_pending': missing['omitted_pending'] + sum(
                   row['comparison_status'] != 'checked' for row in missing['items']),
               # #3192: the same two-layer account for the unchecked ones, so a preview
               # that dropped a row does not silently improve the outlook.
               'omitted_unchecked': missing['omitted_unchecked'] + sum(
                   row['comparison_status'] == 'open' for row in missing['items']),
               'omitted_events': (queue + missing['omitted_events'])[:COMPARISON_EVENT_LIMIT],
               'omitted_events_hidden': hidden + max(
                   0, len(missing['omitted_events']) + len(queue) - COMPARISON_EVENT_LIMIT),
               'preview_only': True,
               'reading': '来源比较摘要只说明所引材料与本版提议的账本状态，不是新证据或可选引文。'
                          '两处不同 URL 不证明独立形成或支持；open 表示没有适用的明确比较记录，'
                          'checked 表示已记录支持比较，contested 表示有冲突记录；都不认证事实。'
                          '按正文事件号找 sources 中的原文；body_events_not_in_packet 没有随包恢复正文，'
                          '不能说已看到它们。omitted_pending 是省略结论中仍有待核对或有冲突的条数，'
                          'omitted_unchecked 只数其中完全没有比较记录（open）的条数，'
                          'omitted_events 按事件号点名哪些结论被省略；点名不等于看过它们；本地用 stories STORY --comparison EVENT 回查当前提议的比较状态。'}
    for index, row in enumerate(missing['items']):
        item = {key: row[key] for key in ('conclusion_event', 'statement', 'comparison_status',
                                         'support_status', 'rank_class', 'next_check')}
        comparisons = [{key: record[key] for key in ('notice_event', 'target', 'relation', 'source_events')}
                       for record in row.get('comparisons', [])]
        body_events = {ref['event'] for ref in row['have']
                       if ref['state'] in ('visible_body', 'counter_evidence')}
        body_events.update(event for record in comparisons for event in record['source_events'])
        item.update(recorded_body_events=sorted(body_events),
                    body_events_not_in_packet=sorted(body_events - restored_events),
                    comparisons=comparisons, comparisons_omitted=row.get('comparisons_omitted', 0))
        candidate = {**preview, 'items': [*preview['items'], item], 'omitted': preview['omitted'] - 1,
                     'omitted_pending': preview['omitted_pending'] - (item['comparison_status'] != 'checked'),
                     'omitted_unchecked': preview['omitted_unchecked'] - (item['comparison_status'] == 'open'),
                     'omitted_events': (queue[index + 1:] + missing['omitted_events'])[:COMPARISON_EVENT_LIMIT],
                     'omitted_events_hidden': hidden + max(
                         0, len(missing['omitted_events']) + len(queue) - index - 1 - COMPARISON_EVENT_LIMIT)}
        if len(json.dumps(candidate, ensure_ascii=False)) > max_characters:
            break  # Keep the ranked prefix; never splice a claim from its pointers.
        preview = candidate
    return preview


def _failures_without_visible_body(db, evidence, events):
    """Join recent source failures to successful searches, not to inferred freshness."""
    recent = [entry for entry in events if entry['kind'] == 'tool_result'][-12:]
    visible = {item['event'] for item in evidence}
    seen = {_source_url_key(entry['payload']['result']['url'])
            for entry in recent if entry['event'] in visible}
    listings = {}
    for key, item in _listed_sources(_search_listings(recent)):
        listings.setdefault(key, item)
    items = []
    for entry in reversed(recent):
        payload = entry['payload']
        action = payload.get('action')
        if not isinstance(action, dict) or action.get('kind') != 'read_source':
            continue
        key = _source_url_key(action.get('url'))
        if key not in listings or key in seen:
            continue
        error = payload.get('error_kind')
        if payload.get('status') == 'executed':
            seen.add(key)
        elif payload.get('status') == 'failed' and _source_failure_kind(error):
            seen.add(key)
            items.append({'event': entry['event'], 'read_url': action['url'],
                          'status': 'failed', 'error_kind': error, 'listed_source': listings[key]})
    if not items:
        return {}
    shown = items[:2]
    for item in shown:
        for row, event in ((item, item['event']), (item['listed_source'], item['listed_source']['search_event'])):
            at, status = _record_time(db.execute('SELECT at FROM inquiry_events WHERE seq=?', (event,)).fetchone()[0])
            row['recorded_at'], row['recorded_at_status'] = at, status
    return {'items': shown, 'omitted': len(items) - len(shown),
            'reading': '这些 URL 在本故事最近十二条工具回执中有成功检索条目和明确的读取失败回执，且本视图未展示该 URL 的正文。按去掉 #片段 的 URL 匹配；检索条目可能晚于失败，不证明当时的读取许可。拒绝执行或未获读取许可不是这类失败；较晚的已执行读取不再列入。无可见正文不等于历史上从未取得正文；失败也不表示材料过期、撤回或不可再读。recorded_at 是 Dojo 入账时刻，非外部材料时刻。连接失败可先检查连通性再重试；格式不支持可另找可读的官方文本；HTTP 失败可先核对状态码及官方入口。'}


def source_read_failures(evidence, events):
    """Show newer failed reads only for URLs with a visible body."""
    visible = {item['event'] for item in evidence}
    latest_body = {}
    recent = [entry for entry in events if entry['kind'] == 'tool_result'][-12:]
    for entry in recent:
        if entry['event'] in visible:
            latest_body[entry['payload']['result']['url']] = entry['event']
    failures = []
    seen = set()
    for entry in reversed(recent):
        payload = entry['payload']
        action = payload.get('action')
        if not isinstance(action, dict) or action.get('kind') != 'read_source':
            continue
        url = action.get('url')
        if not isinstance(url, str) or url not in latest_body or url in seen:
            continue
        seen.add(url)
        error = payload.get('error_kind')
        if (entry['event'] <= latest_body[url] or payload.get('status') != 'failed'
                or not _source_failure_kind(error)):
            continue
        failures.append({'event': entry['event'], 'body_event': latest_body[url], 'error_kind': error})
        if len(failures) == 2:
            break
    return failures


def reading_context(path, story, *, synthetic=False, comparison=None):
    """Read the resume candidates; never re-date or certify a source."""
    from contextlib import closing
    from .knowledge import Knowledge
    path = Path(path)
    if not path.is_file():
        raise ValueError('故事数据库不存在；请选择已有探究记录的库')
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            index = run_index(db)
            runs = _readable_story_runs(index, story, synthetic=synthetic)
            visible_report = _report_visibility(db, runs)
            plan, events = _describe(db, story, synthetic=index[next(iter(runs))]['synthetic'], index=index)
            if comparison is not None:
                result = _story_independence_gap(db, story, index, runs, events, target=comparison)
                if not result['items']:
                    raise ValueError(_comparison_refusal(
                        result.get('target_status') or {'target': comparison}))
                return {'story': story, 'synthetic': plan['synthetic'],
                        'comparison': result['items'][0], 'reading': result['reading']}
            knowledge = Knowledge(db, initialize=False)
            sources = []
            for event in plan['candidate_events']:
                source = knowledge.source(event)
                if source['kind']=='reflection' and source['dependency_status']['state']=='superseded':
                    continue
                view = reading_source(source, story, index)
                view['dependency_status'] = _revision_view(view['dependency_status'], visible_report)
                sources.append(view)
            evidence = evidence_context(knowledge, sources, events)
            failures = source_read_failures(evidence, events)
            failures_without_body = _failures_without_visible_body(db, evidence, events)
            unopened, unopened_omitted, searches_considered = unopened_search_sources(events)
            missing = _story_independence_gap(db, story, index, runs, events)
            history = missing.pop('historical_source_comparisons', None)
            latest_event, latest_at, latest_at_status = _latest_record_time(db, runs)
            return {'story': story, 'synthetic': plan['synthetic'], 'sources': sources,
                    'intent_snapshot_state': plan['intent_snapshot_state'],
                    'user_events_after_intent': plan['user_events_after_intent'],
                    'user_events_after_intent_omitted': plan['user_events_after_intent_omitted'],
                    'source_evidence': evidence,
                    'story_coverage': {'latest_record_event': latest_event, 'latest_record_at': latest_at,
                        'latest_record_at_status': latest_at_status,
                        'decoded_events_in_this_view': len(events),
                        'tool_receipts_in_this_view': sum(1 for entry in events if entry['kind'] == 'tool_result'),
                        'visible_source_bodies': len(evidence),
                        'search_listings_considered': searches_considered,
                        'unopened_search_sources': unopened, 'unopened_omitted': unopened_omitted,
                        **({'missing_independence': missing} if missing['conclusions_in_ledger'] else {}),
                        **({'historical_source_comparisons': history} if history is not None else {})},
                    'story_coverage_reading': '已读指本故事账本里存在实际 read_source 回执（成功时另有可见正文）；未读指同一回执范围里没有该 URL 的读取尝试，失败尝试不算未读，它有自己的下一步。此块只看本故事最近十二个成功检索回执里没有读取尝试的 URL，最多列四条，其余只给省略数；decoded_events_in_this_view 是这份续谈视图解码出的事件总数（含用户报告、模型答复等各类记录），不是读取次数，也不是全量账本计数；tool_receipts_in_this_view 只数其中的工具回执；同一 URL 去掉 #片段 后比较。条目里的 title 照检索返回原文截断到 160 字符。未被列出不表示检索没返回过它，也不表示该 URL 不可读、已撤回或与本次问题无关；被列出也不证明它包含所需材料。续谈后成功的检索回执会恢复该 URL 的读取许可，但当时是否仍可访问、正文是否已变，只能靠新的实际读取回答。latest_record_at 是本故事账本最新一条记录写入 Dojo 的时刻，不是外部材料的时刻：它较旧只说明这份续谈视图旧，不说明外部正文也旧。',
                    **({'source_read_failures': failures,
                        'source_read_failure_reading': '只提示正文和失败回执同时仍可见的情况：两者均须在最近十二条工具回执内，且正文仍在本次候选中。只列同一 URL 的较晚读取失败，最多两条。按账本顺序，不是外部版本顺序。失败未取得新正文，不表示旧正文撤回或仍有效；连接失败可先检查连通性再重试，格式不支持可另找可读的官方文本。空缺不表示从未失败。'} if failures else {}),
                    **({'source_read_failures_without_visible_body': failures_without_body} if failures_without_body else {}),
                    'source_evidence_reading': '仅比较本次候选中可见的读件。同一 URL 的不同正文不表示哪个更新或已撤回。evidence_uses 每份正文最多列本故事最近三条明示引用它作为依据的知识提议，不追踪聊天答复；空列表只表示在上述范围内未找到明示用途，不代表全库从未使用。state 是提议的依赖状态，不判定真伪；current_interpretation 不证明为真，superseded 表示提议已被替代，不等于正文被撤回。',
                    **({'proposal_lookup': '用 stories STORY --proposal EVENT 按 proposal_event 查看本故事提议的报告复核引文。沿可见的 replacement 用 stories STORY --report EVENT 读替代报告原话；仅在明确读取合成故事时保留 --synthetic。'} if any(item['evidence_uses'] for item in evidence) else {}),
                    'report_lookup': '有替代报告号时，用 stories STORY --report EVENT 读本故事的用户原话（合成故事保留 --synthetic）。没有可读替代号时，保留已修订状态和不确定性，不沿用旧报告。',
                    'reading': '这是按续谈候选选出的部分原记录，不是全量账本。用户原话是报告，不是独立核验；模型答复和审查意见不证明事实；失败工具回执不算核验。recorded_at 是此条记录写入 Dojo 的时刻，不是原文中的外部时刻；缺失或无效不等于没有记录。'}
    except sqlite3.Error:
        raise ValueError('无法读取故事数据库；请选择可读取的 Dojo 探究库') from None


def listing(path,*,synthetic=False,story=None):
    """Read-only summary; legacy runs without story metadata remain separate stories."""
    path=Path(path)
    if not path.exists():
        if story:raise ValueError('故事数据库不存在')
        return []
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        index=run_index(db);groups={}
        for r in index.values():
            if r['synthetic'] and not synthetic:continue
            if story is not None and r['story']!=story:continue
            groups.setdefault(r['story'],[]).append(r)
        if story is not None and not groups:raise ValueError('没有可见的故事')
        result=[]
        for sid,runs in groups.items():
            item=describe(db,sid,synthetic=runs[0]['synthetic'])
            if item['opening'] is None and story is None:continue
            value={'story':sid,'synthetic':item['synthetic'],'run_count':len(runs),'latest_run':runs[-1]['run'],
                **{key:item[key] for key in ('intent_snapshot_event','intent_snapshot_state','user_events_after_intent','user_events_after_intent_omitted')},
                'opening':item['opening'],'latest_intent_snapshot':item['latest_intent_snapshot'],
                'state':'historical_reports_and_model_interpretations_not_certified'}
            if story is not None:value['runs']=runs
            result.append(value)
        return sorted(result,key=lambda item:index[item['latest_run']]['start_event'],reverse=True)
    finally:db.close()


def _readable_story_runs(index, story, *, synthetic):
    runs = {run for run, info in index.items() if info['story'] == story}
    identities = {index[run]['synthetic'] for run in runs}
    if not runs or (True in identities and not synthetic):
        raise ValueError('没有可见的故事；请先运行 stories 查找故事标识')
    if len(identities) != 1:
        raise ValueError('故事混有合成/普通身份，不能跨身份读取')
    return runs


def _report_visibility(db, runs):
    def visible_report(seq):
        if type(seq) is not int or not 0 < seq < 2**63:
            return False
        row = db.execute("SELECT run FROM inquiry_events WHERE seq=? AND kind='user'", (seq,)).fetchone()
        return row is not None and row[0] in runs
    return visible_report


def _revision_view(status, visible_report, *, hide_reason=False):
    view = dict(status)
    if 'replacement' in view and not visible_report(view['replacement']):
        view.pop('replacement')
        hide_reason = True
    if hide_reason:
        view.pop('reason', None)
    return view


def reading_report(path, story, event, *, synthetic=False):
    """Read a single same-story user report, without following revisions."""
    from contextlib import closing
    from .knowledge import Knowledge

    unavailable = '没有可见的用户报告'
    path = Path(path)
    if not path.is_file():
        raise ValueError('故事数据库不存在；请选择已有探究记录的库')
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            index = run_index(db)
            try:
                runs = _readable_story_runs(index, story, synthetic=synthetic)
            except ValueError:
                raise ValueError(unavailable) from None

            visible_report = _report_visibility(db, runs)

            if not visible_report(event):
                raise ValueError(unavailable)
            source = reading_source(Knowledge(db, initialize=False).source(event), story, index)
            # Report lookups never expose free-form revision reasons.
            status = _revision_view(source['dependency_status'], visible_report, hide_reason=True)
            source['dependency_status'] = status
            if 'causes' in status:
                causes = [seq for seq in status.pop('causes') if visible_report(seq)]
                if causes:
                    status['causes'] = causes
            return source
    except sqlite3.Error:
        raise ValueError('无法读取故事数据库；请选择可读取的 Dojo 探究库') from None


def reading_proposal(path, story, event, *, synthetic=False):
    """Read one proposal's same-story report signals, not a full review packet."""
    from contextlib import closing
    from .dependencies import DependencyIndex

    unavailable = '没有可见的知识提议'
    path = Path(path)
    if not path.is_file():
        raise ValueError('故事数据库不存在；请选择已有探究记录的库')
    if type(event) is not int or not 0 < event < 2**63:
        raise ValueError(unavailable)
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
            db.execute('BEGIN')
            index = run_index(db)
            try:
                runs = _readable_story_runs(index, story, synthetic=synthetic)
            except ValueError:
                raise ValueError(unavailable) from None
            row = db.execute("SELECT run,payload FROM inquiry_events WHERE seq=? AND kind='knowledge_proposal'", (event,)).fetchone()
            if row is None or row[0] not in runs:
                raise ValueError(unavailable)
            identity = index[row[0]]['synthetic']
            payload = json.loads(row[1])
            if payload.get('synthetic', identity) is not identity:
                raise ValueError(unavailable)
            proposal = payload['proposal']
            deps = DependencyIndex(db, initialize=False)
            status = deps.status(event)
            visible_report = _report_visibility(db, runs)
            signals = []
            for cause in status.get('causes', []):
                if len(signals) == 4:
                    break
                if not visible_report(cause):
                    continue
                report = _revision_view(deps.status(cause), visible_report, hide_reason=True)
                signal = {'report_event': cause,
                          'direct_premise_quotes': [p['quote'] for p in proposal['premises'] if p['event'] == cause]}
                if 'replacement' in report:
                    signal['replacement'] = report['replacement']
                signals.append(signal)
            return {'story': story, 'synthetic': identity, 'proposal_event': event,
                    'statement': proposal['statement'], 'state': status['state'],
                    'report_review': signals,
                    'reading': '只显示最多四条本故事可见的用户报告复核线索，不是全部原因。direct_premise_quotes 是提议直接引用的报告片段；为空时用 report_event 读取原话，不推断提议直接引用。用 stories STORY --report EVENT 读取本故事的报告或可见的首个替代报告（合成故事须显式保留 --synthetic）。没有可读替代报告时保留不确定性。报告、修订和提议状态都不是独立核验，也不判定外部正文版本。'}
    except sqlite3.Error:
        raise ValueError('无法读取故事数据库；请选择可读取的 Dojo 探究库') from None
