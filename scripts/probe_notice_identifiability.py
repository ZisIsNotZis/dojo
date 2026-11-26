"""Which notice-failure explanations an observation scheme can separate. CPU only.

No model request, no product state: this counts partitions over declared
mechanism subsets so a scheme's discriminating power is an explicit claim.
"""
import itertools
import json
from pathlib import Path
import sys

MECHANISMS = ['late', 'unread', 'inconspicuous', 'bypass']

# Channel semantics are definitions, not measurements.
#  d  delivery record: the change/notice was recorded as sent before the plan.
#     Carries no attention - a queued mail, or a board update nobody opened,
#     still sets it.
#  t  attention actually registered before the plan. False when the notice was
#     late, never opened, or present but unnoticed.
#  r  the board or notice was opened before the plan.
#  s  the changed value was reproduced correctly at decision time.
#  c  a stale copy of the old value sat in the artifact the plan was made from.
#  recall  undated after-the-fact probe; true under every subset.
CHANNELS = {
    'd': lambda S: 'late' not in S,
    't': lambda S: not ({'late', 'unread', 'inconspicuous'} & S),
    'r': lambda S: not ({'unread', 'bypass'} & S),
    's': lambda S: not ({'bypass', 'late'} & S),
    'c': lambda S: 'bypass' in S,
    'recall': lambda S: True,
}


def subsets():
    for size in range(len(MECHANISMS) + 1):
        for combo in itertools.combinations(MECHANISMS, size):
            yield frozenset(combo)


def partition(scheme):
    profiles = {}
    for S in subsets():
        key = tuple(bool(CHANNELS[ch](S)) for ch in scheme)
        profiles.setdefault(key, []).append(sorted(S))
    return list(profiles.values())


def pairwise_separated(classes):
    """Pairs of declared SINGLE mechanisms that never share an observation class."""
    seps = set()
    for a, b in itertools.combinations(MECHANISMS, 2):
        if not any([a] in cls and [b] in cls for cls in classes):
            seps.add(tuple(sorted((a, b))))
    return seps


def undistinguished_pairs(classes):
    """Pairs - including the empty (no-failure) subset - sharing an observation class."""
    units = [[m] for m in MECHANISMS] + [[]]
    seen = set()
    for a, b in itertools.combinations(units, 2):
        aa, bb = sorted(a), sorted(b)
        if aa == bb:
            continue
        if any(aa in cls and bb in cls for cls in classes):
            # Canonicalize the two endpoints so the empty (no-failure) subset
            # always sorts into position 0, whichever unit it came from.
            lo, hi = sorted([tuple(aa), tuple(bb)])
            seen.add((lo, hi))
    return sorted(seen)


def subsets_identified(classes):
    return [c[0] for c in classes if len(c) == 1]


def report(scheme):
    classes = partition(scheme)
    all_pairs = {tuple(sorted(p)) for p in itertools.combinations(MECHANISMS, 2)}
    seps = pairwise_separated(classes)
    if len(seps) + len(all_pairs - seps) != len(all_pairs):
        raise SystemExit('partition bookkeeping inconsistent')
    return {
        'scheme': list(scheme),
        'classes': len(classes),
        'largest_class': max(len(c) for c in classes),
        'singletons_identified': subsets_identified(classes),
        'singleton_pairs_distinguishable': sorted(seps),
        'singleton_pairs_collapsed': sorted(all_pairs - seps),
        'collapsed_with_no_failure': [p for p in undistinguished_pairs(classes) if p[0] == ()],
        'multi_mechanism_subsets_identified': [s for s in subsets_identified(classes) if len(s) > 1],
        'unseparated_example': next((c for c in classes if len(c) > 1), None),
    }


def independently_counted(scheme):
    """Second, deliberately literal implementation used to cross-check the first."""
    sig = {}
    for S in subsets():
        row = []
        for ch in scheme:
            if ch == 'd':
                row.append('late' not in S)
            elif ch == 't':
                row.append(not ('late' in S or 'unread' in S or 'inconspicuous' in S))
            elif ch == 'r':
                row.append(not ('unread' in S or 'bypass' in S))
            elif ch == 's':
                row.append(not ('bypass' in S or 'late' in S))
            elif ch == 'c':
                row.append('bypass' in S)
            elif ch == 'recall':
                row.append(True)
            else:
                raise ValueError(ch)
        sig.setdefault(tuple(row), []).append(tuple(sorted(S)))
    return len(sig), max(len(v) for v in sig.values())


SCHEMES = [
    ('d-only', ('d',)),
    ('d+r', ('d', 'r')),
    ('d+s', ('d', 's')),
    ('d+r+s', ('d', 'r', 's')),
    ('d+r+s+c', ('d', 'r', 's', 'c')),
    ('t-only', ('t',)),
    ('t+r', ('t', 'r')),
    ('t+r+s', ('t', 'r', 's')),
    ('t+r+s+c', ('t', 'r', 's', 'c')),
    ('r+s', ('r', 's')),
    ('r+s+c', ('r', 's', 'c')),
    ('s+c', ('s', 'c')),
    ('posthoc-only', ('recall',)),
    ('posthoc+s', ('recall', 's')),
]


def main(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    schemes = SCHEMES
    out = {}
    for name, scheme in schemes:
        rep = report(scheme)
        counted = independently_counted(scheme)
        if (rep['classes'], rep['largest_class']) != counted:
            raise SystemExit('cross-check mismatch for ' + name)
        rep['independent_cross_check'] = {'classes': counted[0], 'largest_class': counted[1]}
        out[name] = rep
    all_pairs = {tuple(sorted(p)) for p in itertools.combinations(MECHANISMS, 2)}
    minimal = None
    for k in range(1, len(CHANNELS) + 1):
        for combo in itertools.combinations(('d', 't', 'r', 's', 'c'), k):
            if pairwise_separated(partition(combo)) >= all_pairs:
                minimal = combo
                break
        if minimal:
            break
    no_failure_pair = ((), ('inconspicuous',))
    without_t = {k: v for k, v in out.items() if 't' not in v['scheme']}
    with_t = {k: v for k, v in out.items() if 't' in v['scheme']}
    invariants = {
        # Under the attention channel t, 'notice present but unnoticed' is NOT the
        # same observation as 'nothing was wrong'; without t it is. This is the
        # measured form of 'delivery is not timely knowing', sharpened from probe-3.
        'inconspicuous_collapses_with_no_failure_when_t_absent': bool(without_t) and all(
            any(tuple(p) == no_failure_pair for p in v['collapsed_with_no_failure']) for v in without_t.values()
        ),
        'inconspicuous_separated_when_t_present': bool(with_t) and all(
            not any(tuple(p) == no_failure_pair for p in v['collapsed_with_no_failure']) for v in with_t.values()
        ),
        'multi_mechanism_subset_identified_in_any_scheme': sorted(
            {tuple(s) for v in out.values() for s in v['multi_mechanism_subsets_identified']}
        ),
    }
    result = {
        'synthetic': True,
        'model_requests': 0,
        'tool_attempts': 0,
        'mechanisms': MECHANISMS,
        'subsets_considered': 2 ** len(MECHANISMS),
        'schemes': out,
        'cheapest_all_pair_scheme': list(minimal) if minimal else None,
        'invariants': invariants,
        'scope': (
            'Only the partition induced by declared deterministic channels over declared '
            'mechanism subsets. Values are definitions, not measurements; a fifth explanation '
            '(the change never reached that group plan) is not modeled. No notice latency, '
            'rework cost, reader behavior or feasibility of collecting a channel is certified.'
        ),
    }
    (root / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = [
        {'scheme': k, 'classes': v['classes'], 'largest': v['largest_class'],
         'distinguishable': len(v['singleton_pairs_distinguishable']),
         'collapsed': v['singleton_pairs_collapsed'],
         'no_failure_collapse': v['collapsed_with_no_failure'],
         'multi_identified': v['multi_mechanism_subsets_identified']}
        for k, v in out.items()
    ]
    print(json.dumps({'rows': rows, 'cheapest': result['cheapest_all_pair_scheme'],
                      'invariants': invariants}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1]))
