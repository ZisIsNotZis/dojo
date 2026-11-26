"""Which conclusion most needs a second, separately readable source?

The old context view answers "was this URL read?" per receipt. This view starts
from the conclusions a story already recorded (`knowledge_proposal` premises
with role `evidence`) and asks, per conclusion, how many *distinct* materials
have a visible body. It is a checking order, not a truth verdict: a conclusion
with no support is not thereby false, and a conclusion with two URLs is not
thereby true. Two URLs are two materials, not two witnesses -- the ledger has
no independence-group field, so author identity is never inferred here. An
explicit review notice can record what was compared for a particular version.
"""
from .stories import _source_failure_kind, _source_url_key

# Lower sorts first. `no_source` is the widest gap; a declared source that was
# read and failed at least names a concrete next attempt; `unknown` means the
# ledger itself cannot be counted (a premise event is missing or unreadable),
# which needs repair before a retry is even meaningful; `single_group` already
# has one body but repeats the same URL; `single_source` is one distinct
# material; `independent` is two distinct materials with bodies.
RANK_ORDER = ('no_source', 'missing_body', 'contested', 'mixed', 'unknown',
              'single_source', 'single_group', 'independent')

GAP = {
    'no_source': '这条结论未引用带可见正文的工具回执；用户报告、模型提议与审议意见都不算独立核验。',
    'missing_body': '提议引用了明确的读取失败回执，没有引用该来源的成功正文；失败不等于材料过期或不可再读。',
    'mixed': '提议引用了可读正文，也引用了另一来源的失败回执；该失败回执不提供正文。',
    'unknown': '有前提事件号无法在本视图里解析，无法确定该结论有几处独立依据；先查清这些事件号，再谈补来源。',
    'single_group': '两处以上前提读的是同一 URL（去掉 #片段后同一份材料），读两次仍算一处，尚缺第二份独立材料。',
    'single_source': '仅引用一处不同 URL 的可见正文，尚缺第二处独立材料。',
    'independent': '已引用两处以上不同 URL 的可见正文；材料数量不证明各自支持这条说法或互相独立。',
    'contested': '有明确比较记录指出正文与本说法冲突；反向正文不算第二处支撑。',
    'checked': '本版的两处引用已有独立形成且各自支持的比较记录；这是已记录的判断，不认证结论为真。',
}

NEXT = {
    'no_source': '为这条结论指名一份可读的官方或一手材料，并实际读取成功；不要用同一模型的另一段说法充当第二处。',
    'unknown': '先按事件号查清每条前提属于哪条记录或哪个故事，再决定补读哪份材料；本视图看不到不等于账本没有。',
    'single_group': '找一份独立形成、实际支持这条结论的材料；同页面的 #片段不算第二处。',
    'single_source': '补一份不同来源的材料，核对它是否独立形成并实际支持这条结论；换一个网址重刊同一份材料不算。',
    'independent': '先核两份材料是否独立形成、是否各自支持这条说法；不因有两个 URL 就跳过核对。',
}

COMPARISON_DETAIL_LIMIT = 4
HISTORICAL_COMPARISON_LIMIT = 4

READING = ('按知识提议里 role=evidence 的前提事件计数；用户报告、模型提议、审议意见与嵌套提议不计为独立支持。'
           '两处前提读同一 URL（去 #片段）只算一处材料。按所引账本事件统计，不限于上面恢复的候选正文。'
           '排序是核对顺序，不是真假判定；乱序或缺席不表示某结论已被证伪。'
           '账本时刻、读取失败与检索回执都不能证明外部材料陈旧或撤回：freshness 一律 unknown，除非有外部版本对照。'
           '本块只数本故事内未被替代提议的明示引用；其他读件即使 URL 相同，也不会替提议补上引用。'
           '仅有绑定提议版本与两个正文回执号的明确比较记录，才标为 checked 或 contested；'
           '普通复核、判断理由的自由文本和两个 URL 本身都不能改变比较状态。')


def evidence_events(proposal):
    premises = proposal.get('premises')
    if not isinstance(premises, list):
        return set()
    return {p['event'] for p in premises if isinstance(p, dict) and p.get('role') == 'evidence'
            and type(p.get('event')) is int}


def read_receipts(events):
    """All source reads in this story: visible bodies and explicit failures."""
    reads = {}
    for entry in events:
        if entry['kind'] != 'tool_result':
            continue
        payload = entry['payload']
        action = payload.get('action')
        if not isinstance(action, dict) or action.get('kind') != 'read_source':
            continue
        url = action.get('url')
        key = _source_url_key(url)
        if not key:
            continue
        result = payload.get('result')
        if (payload.get('status') == 'executed' and isinstance(result, dict)
                and result.get('url') == url and isinstance(result.get('text'), str)
                and result['text'].strip()):
            reads[entry['event']] = {'url': url, 'key': key, 'state': 'visible_body'}
        elif payload.get('status') == 'failed' and _source_failure_kind(payload.get('error_kind')):
            reads[entry['event']] = {'url': url, 'key': key, 'state': 'read_failed',
                                     'error_kind': payload['error_kind']}
    return reads


def _next_check(rank, have, failed):
    if rank not in ('missing_body', 'mixed'):
        return NEXT[rank]
    actions = {}
    for item in have:
        if item['state'] != 'read_failed' or _source_url_key(item['url']) not in failed:
            continue
        error = item['error_kind']
        advice = {'source_type': '格式不支持，另找可读的官方文本',
                  'source_connect': '检查连通性后重试'}.get(error, '核对 HTTP 状态码和官方入口')
        actions[(item['url'], error)] = advice
    return '；'.join(f'{url}（{error}）：{advice}' for (url, error), advice in actions.items()) + '。取得正文后，核对它是否支持这条结论。'


def _gap_text(rank, have):
    """The fixed sentence, plus what was actually found when it adds a fact."""
    text = GAP[rank]
    counts = {}
    for item in have:
        counts[item['state']] = counts.get(item['state'], 0) + 1
    if rank == 'no_source' and counts.get('record_not_a_source_read'):
        # A computation or an experiment is work, not a readable material. Say
        # that plainly, so the reader does not think the ledger is empty.
        text = ('这条结论引用了非来源读取记录（例如实验、检索或计算回执），但没有引用可独立阅读的来源正文；'
                '记录里有工作，但不由另一份材料支撑。')
    return text


def _classify(proposal, reads, kinds, *, elsewhere=None, counter_events=()):
    raw = proposal.get('premises')
    # Legacy or hand-written rows can carry a malformed premise list. Unreadable
    # is counted as unreadable, not as zero support and not as one.
    referenced = [p for p in raw if isinstance(p, dict)] if isinstance(raw, list) else []
    malformed = 0 if isinstance(raw, list) and len(referenced) == len(raw) else 1
    evidence = [p for p in referenced if p.get('role') == 'evidence']
    have, keys, failed = [], set(), set()
    unresolved = nested = this_story_hidden = other_story = non_source_records = 0
    unattributed = 0
    for premise in evidence:
        event = premise.get('event')
        row = kinds.get(event) if type(event) is int else None
        if row == 'tool_result' and event in reads:
            receipt = reads[event]
            if receipt['state'] == 'visible_body':
                state = 'counter_evidence' if event in counter_events else 'visible_body'
                if state == 'visible_body':
                    keys.add(receipt['key'])
                have.append({'event': event, 'kind': 'tool_result', 'url': receipt['url'], 'state': state})
            else:
                failed.add(receipt['key'])
                have.append({'event': event, 'kind': 'tool_result', 'url': receipt['url'],
                             'state': 'read_failed', 'error_kind': receipt['error_kind']})
        elif row is None:
            # Not decoded in this story: either the event number does not exist
            # at all, or it is a record this view does not show (another story,
            # or a kind outside the resume candidate set). Only the first is
            # unresolvable; the rest are known rows that this view cannot weigh.
            where = elsewhere(event) if elsewhere is not None else {'exists': False}
            if not where.get('exists'):
                unresolved += 1
                have.append({'event': event, 'kind': None, 'state': 'unresolved'})
            elif where.get('same_story'):
                this_story_hidden += 1
                have.append({'event': event, 'kind': where.get('kind'),
                             'state': 'this_story_not_shown'})
            elif where.get('story') is None:
                # The row exists but no start event tells us which story owns it
                # (a legacy library). Say that, rather than name another story.
                unattributed += 1
                have.append({'event': event, 'kind': where.get('kind'),
                             'state': 'unattributed_record_not_counted'})
            else:
                other_story += 1
                have.append({'event': event, 'kind': where.get('kind'),
                             'story': where.get('story'), 'state': 'other_story_record_not_counted'})
        elif row in ('user', 'reflection', 'epistemic_check', 'distillation'):
            have.append({'event': event, 'kind': row, 'state': 'not_independent_support'})
        elif row == 'tool_result':
            # A real receipt, but not a readable source body: an experiment, a
            # search listing, a computation. It is evidence of work, not an
            # independently readable material, so it counts as neither.
            non_source_records += 1
            have.append({'event': event, 'kind': row, 'state': 'record_not_a_source_read'})
        elif row == 'knowledge_proposal':
            nested += 1
            have.append({'event': event, 'kind': row, 'state': 'nested_proposal_not_expanded'})
        else:
            unresolved += 1
            have.append({'event': event, 'kind': row, 'state': 'unresolved'})

    visible = {item['event'] for item in have if item['state'] == 'visible_body'}
    failed -= keys
    if unresolved or malformed or other_story or this_story_hidden or unattributed:
        rank = 'unknown'
    elif not keys and not failed:
        rank = 'no_source'
    elif not keys:
        rank = 'missing_body'
    elif failed:
        rank = 'mixed'
    elif len(keys) >= 2:
        rank = 'independent'
    elif len(visible) >= 2:
        rank = 'single_group'
    else:
        rank = 'single_source'
    status = {'no_source': 'no_independent_support', 'missing_body': 'declared_source_unread',
              'mixed': 'partially_supported_with_failure', 'unknown': 'count_unresolved',
              'single_group': 'one_material_repeated', 'single_source': 'single_material',
              'independent': 'two_distinct_materials'}[rank]
    return {'rank_class': rank, 'support_status': status, 'have': have,
            'distinct_material_sources': sorted(k for k in keys if k is not None),
            'unread_declared_urls': sorted(k for k in failed if k is not None),
            'evidence_premises': len(evidence), 'assumption_premises': len(referenced) - len(evidence),
            'unresolved_premises': unresolved, 'nested_proposals': nested,
            'premises_in_this_story_not_shown': this_story_hidden,
            'non_source_records': non_source_records,
            'other_story_premises': other_story,
            'unattributed_premises': unattributed,
            'malformed_premise_list': malformed,
            'gap': _gap_text(rank, have), 'next_check': _next_check(rank, have, failed)}


def _comparison_rows(events, reads, notices, successors):
    """Project exact comparison anchors; ignore legacy unclassified notices."""
    proposals = {e['event']: e['payload']['proposal'] for e in events
                 if e['kind'] == 'knowledge_proposal' and isinstance(e['payload'].get('proposal'), dict)}
    cited = {event: evidence_events(p) for event, p in proposals.items()}
    by_version = {}
    for notice, data in notices:
        comparison = data.get('comparison')
        target = data.get('target')
        if not isinstance(comparison, dict) or type(target) is not int or target not in proposals:
            continue
        relation, pair = comparison.get('relation'), comparison.get('events')
        if (relation not in ('supports_independently', 'conflicts') or not isinstance(pair, list)
                or len(pair) != 2 or any(type(e) is not int for e in pair)
                or pair[0] == pair[1] or max(target, *pair) >= notice
                or not all(reads.get(e, {}).get('state') == 'visible_body' for e in pair)):
            continue
        basis, other = pair
        if basis not in cited[target]:
            continue
        if relation == 'supports_independently':
            if other not in cited[target] or reads[basis]['key'] == reads[other]['key']:
                continue
        elif other not in cited[target] and other <= target:
            continue
        reason = data.get('reason')
        item = {'notice_event': notice, 'target': target, 'relation': relation,
                'source_events': pair, 'reason': reason[:800] if isinstance(reason, str) else '',
                'reason_truncated': isinstance(reason, str) and len(reason) > 800}
        by_version.setdefault(target, []).append(item)
        if relation != 'conflicts':
            continue
        # An unresolved comparison remains relevant to a restatement only
        # while every successor retains the exact statement and both anchors.
        version = target
        while True:
            new = successors.get(version)
            if (new not in proposals or new <= version or not set(pair) <= cited[new]
                    or proposals[new].get('statement') != proposals[version].get('statement')):
                break
            by_version.setdefault(new, []).append(item)
            version = new
    return by_version


def _historical_support_comparisons(events, comparisons, successors):
    """Keep accepted support records on their old version and exact reads."""
    replaces = {}
    for entry in events:
        if entry['kind'] != 'knowledge_proposal':
            continue
        proposal = entry['payload'].get('proposal')
        if not isinstance(proposal, dict):
            continue
        old, new = proposal.get('revises'), entry['event']
        if type(old) is int and old < new and successors.get(old) == new:
            # New is a proposal in this story. Old and its body events must
            # also be here to have a validated comparison row below.
            replaces[old] = new
    items = []
    for old, new in replaces.items():
        for record in comparisons.get(old, ()):
            if (record['relation'] != 'supports_independently' or record['target'] != old
                    or record['notice_event'] >= new):
                continue
            items.append({key: record[key] for key in ('notice_event', 'target', 'relation', 'source_events')}
                         | {'replacement_event': new, 'applies_to': 'target_only'})
    if not items:
        return None
    items.sort(key=lambda item: item['notice_event'], reverse=True)
    return {'items': items[:HISTORICAL_COMPARISON_LIMIT],
            'omitted': max(0, len(items) - HISTORICAL_COMPARISON_LIMIT),
            'preview_only': True,
            'reading': '旧版支持比较只适用于 target 所指的已替代提议，不担保 replacement_event 或任何新版。'
                       '历史指针不是新证据或可引用锚点，不改变新版的比较状态或下一步。'
                       'source_events 是原正文回执号；只有在 sources 中找到对应记录才算看到正文。'}


def independence_gap(events, *, cap=5, lookup=None, revised=(), successors=None, notices=(), target=None):
    """Rank recorded conclusions; comparison state is separate from URL counts."""
    reads = read_receipts(events)
    kinds = {entry['event']: entry['kind'] for entry in events}
    successors = successors or {}
    comparisons = _comparison_rows(events, reads, notices, successors)
    rows = []
    for entry in events:
        version = entry['event']
        if (entry['kind'] != 'knowledge_proposal' or version in revised
                or (target is not None and version != target)):
            continue
        proposal = entry['payload'].get('proposal')
        if not isinstance(proposal, dict):
            continue
        records = comparisons.get(version, [])
        conflicts = [record for record in records if record['relation'] == 'conflicts']
        classified = _classify(proposal, reads, kinds, elsewhere=lookup,
                               counter_events={r['source_events'][1] for r in conflicts})
        row = {'conclusion_event': version, 'statement': proposal.get('statement'),
               'comparison_status': 'open', **classified}
        if conflicts:
            basis, other = conflicts[-1]['source_events']
            row.update(rank_class='contested', support_status='contested_basis_pending_review',
                       comparison_status='contested', gap=GAP['contested'],
                       next_check=f'判清事件 #{basis} 与 #{other} 的冲突：核对口径、时点或原始记录，再决定是否修订结论。')
        elif records:
            row['comparison_status'] = 'checked'
            if classified['rank_class'] == 'independent':
                row.update(gap=GAP['checked'], next_check=None)
        if records:
            relevant = conflicts or records
            row['comparisons'] = relevant[-COMPARISON_DETAIL_LIMIT:][::-1]
            omitted = len(relevant) - len(row['comparisons'])
            row['comparisons_omitted'] = omitted
            if conflicts and omitted:
                # A count alone cannot identify a hidden conflict. Give one
                # exact pointer without unbounding the resume view.
                hidden = conflicts[omitted - 1]
                basis, other = hidden['source_events']
                row['next_check'] += (f'另有 {omitted} 条较早的冲突未展开；'
                                      f'最近一条是通知 #{hidden["notice_event"]}（事件 #{basis} 与 #{other}）。')
        row['independence_basis'] = 'distinct_source_url; not author, witness or session identity'
        row['freshness'] = 'unknown'
        row['freshness_reason'] = ('账本时刻、读取失败与检索回执只说明本库记录，不说明外部材料何时变化；'
                                   '无外部版本对照不判新旧。')
        rows.append(row)
    rows.sort(key=lambda row: (RANK_ORDER.index(row['rank_class']),
                               row['comparison_status'] == 'checked', row['conclusion_event']))
    shown = rows[:cap]
    dropped = rows[cap:]
    # #3192: a bare `omitted` count cannot say who was dropped or whether those rows were
    # unchecked, so a reader -- and a model handed only this block -- cannot cite what it
    # cannot see. Name the dropped conclusions and count the ones with no comparison record.
    # `omitted_pending` keeps its wider meaning: open plus contested.
    dropped_events = [row['conclusion_event'] for row in dropped]
    history = _historical_support_comparisons(events, comparisons, successors) if successors else None
    return {'items': shown, 'omitted': len(rows) - len(shown),
            'omitted_pending': sum(row['comparison_status'] != 'checked' for row in dropped),
            'omitted_unchecked': sum(row['comparison_status'] == 'open' for row in dropped),
            'omitted_events': dropped_events[:COMPARISON_DETAIL_LIMIT],
            'omitted_events_hidden': max(0, len(dropped_events) - COMPARISON_DETAIL_LIMIT),
            'conclusions_in_ledger': len(rows), 'reading': READING,
            **({'historical_source_comparisons': history} if history is not None else {})}
