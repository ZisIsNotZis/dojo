"""Adversarial collision test for the `r+s` claim from the identifiability probe.

CPU only, 0 model requests, 0 tools, 0 participants. Synthetic.

Why this exists: the identifiability probe counted partitions over declared
channels and reported that `r+s` separates all six singleton explanation pairs.
That result restates its own formulas, because they make `s` a pure function of
{bypass, late} and `r` a pure function of {unread, bypass}. Once an ALTERNATE
INFORMATION ROUTE is allowed the formulas stop being the whole story and the
wide claim has an admissible counterexample. This probe enumerates the smallest
such space and reports, for each collision, the cheapest field that breaks it.
"""
import itertools
import json
from pathlib import Path
import sys

MECHANISMS = ['late', 'unread', 'inconspicuous', 'bypass']

COLLEAGUE = 'colleague_told_value'   # value came from a person, not the artifact
TIMELY = 'value_already_current'     # the plan already used the right value

# Declared channels, same formulas as probe_notice_identifiability.py.
BASE = {
    'd': lambda S: 'late' not in S,
    't': lambda S: not ({'late', 'unread', 'inconspicuous'} & S),
    'r': lambda S: not ({'unread', 'bypass'} & S),
    's': lambda S: not ({'bypass', 'late'} & S),
    'c': lambda S: 'bypass' in S,
    'recall': lambda S: True,
}

# Candidate fields a team could put in a record. Definitions only - not a claim
# that any team collects them.
EXTRA = {
    'who': lambda tr: bool(tr.get(COLLEAGUE)),
    'ts': lambda tr: bool(tr.get('late_arrived')),
}

ALL_CHANNELS = ('d', 't', 'r', 's', 'c', 'recall', 'who', 'ts')


def declared(S):
    return {m: (m in S) for m in MECHANISMS}


def with_colleague(S):
    tr = declared(S)
    tr[COLLEAGUE] = True
    return tr


def with_timely_value(S):
    """A late notice, but the value used in the plan was already the new one."""
    tr = declared(S)
    tr[TIMELY] = True
    tr['late_arrived'] = True
    return tr


def usable(tr):
    """A route only exists where its own precondition holds."""
    if tr.get(COLLEAGUE):
        # Someone can only pass a correct value along if they actually knew it.
        return not tr.get('unread') and not tr.get('inconspicuous')
    if tr.get(TIMELY):
        return bool(tr.get('late'))
    return True


def value(tr, ch):
    """An extra route overrides exactly the channel it makes uninformative."""
    if ch == 's' and (tr.get(COLLEAGUE) or tr.get(TIMELY)):
        return True
    if ch in EXTRA:
        return bool(EXTRA[ch](tr))
    return bool(BASE[ch]({m for m in MECHANISMS if tr.get(m)}))


def signature(tr, scheme):
    return tuple(value(tr, ch) for ch in scheme)


def all_subsets():
    for k in range(len(MECHANISMS) + 1):
        for combo in itertools.combinations(MECHANISMS, k):
            yield frozenset(combo)


def build_space():
    """(label, cause-set, trace). Labels are (kind, *causes)."""
    space = []
    for S in all_subsets():
        space.append((('declared',) + tuple(sorted(S)), S, declared(S)))
    for S in all_subsets():
        for kind, make in (('colleague', with_colleague), ('timely', with_timely_value)):
            tr = make(S)
            if usable(tr):
                space.append(((kind,) + tuple(sorted(S)), S, tr))
    return space


def collisions(space, scheme):
    """Two different accounts producing the same observation."""
    buckets = {}
    for label, S, tr in space:
        buckets.setdefault(signature(tr, scheme), []).append((label, S, tr))
    out = []
    for sig, members in buckets.items():
        for (la, _sa, _ta), (lb, _sb, _tb) in itertools.combinations(members, 2):
            if la == lb:
                continue
            out.append({'sig': list(sig), 'a': list(la), 'b': list(lb)})
    return out


def find(space, label):
    return next((tr for lab, _S, tr in space if lab == label), None)


def cheapest_breakers(space, scheme, label_a, label_b):
    tr_a, tr_b = find(space, label_a), find(space, label_b)
    return [ch for ch in ALL_CHANNELS
            if ch not in scheme
            and signature(tr_a, tuple(scheme) + (ch,)) != signature(tr_b, tuple(scheme) + (ch,))]


def main(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    space = build_space()
    scheme = ('r', 's')
    rows = [dict(c, breaks_with=cheapest_breakers(space, scheme, tuple(c['a']), tuple(c['b'])))
            for c in collisions(space, scheme)]

    declared_only = [(lab, S, tr) for lab, S, tr in space if lab[0] == 'declared']
    declared_collisions = collisions(declared_only, scheme)

    headline = []
    for la, lb in [
        (('colleague', 'bypass'), ('declared', 'unread')),
        (('timely', 'late'), ('declared',)),
    ]:
        tr_a, tr_b = find(space, la), find(space, lb)
        headline.append({
            'a': list(la),
            'b': list(lb),
            'sig_a': list(signature(tr_a, scheme)) if tr_a is not None else None,
            'sig_b': list(signature(tr_b, scheme)) if tr_b is not None else None,
            'merge_under_r_plus_s': (tr_a is not None and tr_b is not None
                                     and signature(tr_a, scheme) == signature(tr_b, scheme)),
            'breaks_with': cheapest_breakers(space, scheme, la, lb),
        })

    result = {
        'synthetic': True,
        'model_requests': 0,
        'tool_attempts': 0,
        'scheme_under_test': list(scheme),
        'hypotheses_considered': len(space),
        'declared_subsets_considered': len(declared_only),
        'declared_only_collisions_under_r_plus_s': declared_collisions,
        'collisions_with_routes_under_r_plus_s': rows,
        'headline_collisions': headline,
        'scope': (
            'Only the partition induced by declared deterministic channels plus two declared '
            'alternate routes (a colleague supplies the value; the value used was already '
            'current when the late notice arrived). The routes are legal combinations, not '
            'measured frequencies. No claim about which route actually occurs, no reader '
            'behavior, no rework effect, no assertion that any team collects who/ts.'
        ),
    }
    (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'declared_only_collisions': len(declared_collisions),
                      'route_collision_count': len(rows),
                      'headline': headline}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
