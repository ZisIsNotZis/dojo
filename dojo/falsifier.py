"""Compile a proposal's falsifier into an enumerated predicate, then let a
counterexample receipt downgrade that proposal to needs_review.

Scope limits that matter:
- The prose `falsifier` is NOT understood. A predicate is only accepted when it
  carries the sha256 of the exact prose it was written for, so editing the prose
  invalidates the predicate instead of silently inheriting it.
- Predicates reuse experiments.parameter_sweep's AST whitelist; no arbitrary code.
- A hit is a point where the predicate holds AND the receipt's own assertion
  failed there (r48). A predicate that only holds where the experiment's
  assertion also held has been contradicted by nothing; it is not a hit.
- Rows written before r48 keep the older meaning of `hits`; every new product
  carries CRITERIA_VERSION so two readings are never silently compared.
- A hit only changes dependency status to needs_review. It never calls a proposal
  false and never rewrites its statement: that stays a model/human judgement.
"""
import hashlib
import itertools
import json

from .experiments import parameter_sweep

CHECK_KEYS = {'falsifier_sha256', 'parameters', 'derived', 'predicate', 'predicate_fails_at'}
# The meaning of a stored `hits` count changed in r48: a hit used to be any point
# where the candidate predicate held, and now it must also be a point where the
# receipt's own assertion failed. Rows written before r48 keep the old meaning,
# so every product of the bridge carries this version and old readings are not
# silently comparable with new ones.
CRITERIA_VERSION = 'r48'
HIT_DEFINITION = 'predicate_holds_and_receipt_assertion_fails'
# The digest is derived from the prose, not authored: a caller cannot hash text
# (no tool returns sha256), so requiring it made the predicate unreachable.
REQUIRED_CHECK_KEYS = CHECK_KEYS - {'falsifier_sha256'}


def falsifier_digest(text):
    if not isinstance(text, str):
        raise ValueError('falsifier text must be a string')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _require_declared_failure_point(check):
    """The candidate must name a grid point where its own predicate is false.

    Every refusal below is a refusal, never a miss: a check that cannot exhibit
    a failing point has not been shown falsifiable, which is not the same as a
    predicate that was enumerated and survived.
    """
    point = check['predicate_fails_at']
    grid = check['parameters']
    if not isinstance(point, dict) or not isinstance(grid, dict):
        raise ValueError('failure_point_parameters_do_not_match_grid')
    if set(point) != set(grid):
        raise ValueError('failure_point_parameters_do_not_match_grid: declared '
                         + ', '.join(sorted(grid)) + '; got ' + ', '.join(sorted(point)))
    for name, value in point.items():
        values = grid[name] if isinstance(grid[name], list) else [grid[name]]
        if not any(value == candidate and type(value) is type(candidate) for candidate in values):
            raise ValueError('failure_point_is_not_in_declared_grid: ' + name + '=' + repr(value))
    from .experiments import expression as _expression
    data = dict(point)
    try:
        for key, formula in check['derived'].items():
            data[key] = _expression(formula, data, indicators=True)
        holds = bool(_expression(check['predicate'], data, assertion=True, indicators=True))
    except (ValueError, SyntaxError, ArithmeticError) as exc:
        raise ValueError('falsifier predicate does not compile: ' + str(exc)) from None
    if holds:
        raise ValueError('declared_failure_point_does_not_falsify_predicate: predicate holds at '
                         + repr(point) + ', so this is not a point where the candidate is refuted')


def compile_check(check, falsifier_text):
    """Validate a submitted predicate. Any failure raises with the reason.

    `falsifier_sha256` may be omitted: it is the digest of `falsifier_text`, so
    the server computes it. When it is supplied it must match -- that is the one
    guard that stops a predicate written for other prose from being inherited,
    and computing a missing digest does not weaken it.

    `predicate_fails_at` is required and evaluated. A predicate the candidate
    cannot exhibit a failure point for is not a falsifier: `1>0` and
    `to_second>=0` hold at every point, so no declaration can be made for them
    and they can never be scored. This is not pattern-matching on the
    expression; it makes the evidence of falsifiability unobtainable for a
    tautology.
    """
    if not isinstance(check, dict) or set(check) - CHECK_KEYS or not REQUIRED_CHECK_KEYS <= set(check):
        raise ValueError('falsifier_check needs exactly: ' + ', '.join(sorted(CHECK_KEYS))
                         + ' (falsifier_sha256 may be omitted)')
    digest = falsifier_digest(falsifier_text)
    if 'falsifier_sha256' in check and check['falsifier_sha256'] != digest:
        raise ValueError('falsifier_check is bound to different falsifier text; rewrite the predicate')
    if not isinstance(check['predicate'], str) or not check['predicate'].strip():
        raise ValueError('falsifier_check needs a non-empty predicate')
    # Reuse the experiment grid engine so an uncompilable predicate is refused
    # here with the same reasons the tool would give, not silently skipped.
    try:
        result = parameter_sweep(check['parameters'], check['derived'], check['predicate'])
    except (ValueError, SyntaxError, ArithmeticError) as exc:
        raise ValueError('falsifier predicate does not compile: ' + str(exc)) from None
    _require_declared_failure_point(check)
    # Keep exactly CHECK_KEYS so the stored form re-validates on read.
    return {'falsifier_sha256': digest,
            'parameters': check['parameters'], 'derived': check['derived'], 'predicate': check['predicate'],
            'predicate_fails_at': check['predicate_fails_at']}


def _same_grid(declared, domain):
    """Same parameter names AND same values, order-insensitive.

    Names alone do not identify a grid: {N:[20,50]} and {N:[20,51]} are the same
    names and different experiments.
    """
    def key(values):
        return sorted(repr(v) for v in values)
    return (sorted(declared) == sorted(domain)
            and all(key(declared[name]) == key(domain[name]) for name in declared))


def evaluate(check, domain, derived=None, assertion=None):
    """Enumerate the falsifier over a receipt's actual searched domain.

    The declared parameter grid must match the searched grid exactly -- names
    and values -- and the declared derived formulas must match the receipt's,
    or the predicate would be scored on a model the receipt never computed.
    Each mismatch is refused with its own reason rather than evaluated, so it
    can never be read as a hit or as a miss.

    A hit is a point where the candidate predicate holds **and** the receipt's
    own `assertion` fails there. r46 found on-disk hits that held only where the
    receipt's assertion held too: the experiment had contradicted nothing and
    the proposal was downgraded anyway. `assertion` is required for that reason.
    """
    if not isinstance(domain, dict) or set(domain) != set(check['parameters']):
        return {'status': 'refused', 'reason': 'parameter_names_do_not_match_receipt_domain',
                'declared': sorted(check['parameters']), 'receipt': sorted(domain) if isinstance(domain, dict) else None}
    # Names alone are not the grid. A check declaring the same keys with other
    # values would be scored on points the experiment never computed, which is
    # the same kind of error as a different derived model: refused, not scored.
    if not _same_grid(check['parameters'], domain):
        return {'status': 'refused', 'reason': 'parameter_values_do_not_match_receipt_domain',
                'declared': check['parameters'], 'receipt': domain}
    if derived is None and check['derived']:
        # A receipt that never recorded its derived formulas cannot confirm that
        # the predicate was scored on the same quantities the experiment used.
        return {'status': 'refused', 'reason': 'receipt_does_not_record_derived_definitions'}
    if derived is not None:
        if not isinstance(derived, dict):
            return {'status': 'refused', 'reason': 'receipt_does_not_record_derived_definitions'}
        differing = {name: {'declared': formula, 'receipt': derived.get(name)}
                     for name, formula in check['derived'].items() if derived.get(name) != formula}
        if differing:
            return {'status': 'refused', 'reason': 'derived_formula_does_not_match_receipt_model',
                    'differing': differing}
    try:
        result = parameter_sweep(domain, check['derived'], check['predicate'])
    except (ValueError, SyntaxError, ArithmeticError) as exc:
        return {'status': 'refused', 'reason': 'predicate_failed_on_receipt_domain: ' + str(exc)}
    if assertion is None or not isinstance(assertion, str) or not assertion.strip():
        # The failure side of the definition cannot be computed. Falling back to
        # 'the predicate holds' would restore the pre-r48 meaning precisely on the
        # receipts where the strict reading matters, so this is a refusal.
        return {'status': 'refused', 'reason': 'receipt_does_not_record_the_assertion_that_failed'}
    from .experiments import expression as _expression
    # The receipt's assertion belongs to the receipt's model, not the candidate's:
    # a candidate that declares fewer derived formulas than the receipt computed
    # is still scored (that limit is reported as derived_compared, not refused),
    # so scoring the assertion under the candidate's narrower model would make a
    # legitimate check uncompilable.
    receipt_model = dict(derived) if isinstance(derived, dict) else {}
    strict_hits = 0
    predicate_only = 0
    strict_examples = []
    try:
        for values in itertools.product(*domain.values()):
            point = dict(zip(domain, values))
            candidate_data = dict(point)
            for key, formula in check['derived'].items():
                candidate_data[key] = _expression(formula, candidate_data, indicators=True)
            if not _expression(check['predicate'], candidate_data, assertion=True, indicators=True):
                continue
            # The predicate held here. It counts only if the receipt's own
            # assertion failed at the same point: that is what makes the receipt
            # a counterexample to the candidate rather than an unrelated run.
            predicate_only += 1
            receipt_data = dict(point)
            for key, formula in receipt_model.items():
                receipt_data[key] = _expression(formula, receipt_data, indicators=True)
            if not _expression(assertion, receipt_data, assertion=True, indicators=True):
                strict_hits += 1
                if len(strict_examples) < 2:
                    strict_examples.append({'parameters': point,
                                            'derived': {k: receipt_data[k] for k in receipt_model}})
    except (ValueError, SyntaxError, ArithmeticError) as exc:
        return {'status': 'refused', 'reason': 'receipt_assertion_does_not_compile: ' + str(exc)}
    # r62: whether the receipt's own assertion ever held anywhere on the receipt's
    # own grid. When it holds nowhere, every point where the candidate predicate
    # holds is also a 'hit', so the hit carries no discrimination: the candidate
    # was not refuted by this experiment, it merely agrees with a claim that was
    # false at every searched point. Refused, not `not_hit`: nothing usable was
    # scored (same convention as the refusals above). A candidate that never
    # holds keeps its `not_hit` reading untouched -- that record has its own use.
    try:
        receipt_passed = parameter_sweep(domain, receipt_model, assertion)['passed']
    except (ValueError, SyntaxError, ArithmeticError):
        receipt_passed = None
    if receipt_passed == 0 and strict_hits > 0:
        return {'status': 'refused', 'reason': 'receipt_assertion_never_held_on_its_own_grid',
                'receipt_passed': 0, 'hits': strict_hits}
    hits = strict_hits
    # Coverage, not a verdict: only the candidate's own declared formulas are
    # compared, so a candidate that declares fewer of the receipt's formulas is
    # scored on a narrower model and still passes. Reporting which formulas were
    # actually compared keeps that limit visible without refusing a candidate
    # that only cares about one quantity. A stricter key-set check was rejected:
    # it changed no on-disk verdict (0 of 12 sampled receipts) and would refuse
    # legitimate single-quantity checks.
    compared = sorted(name for name, formula in check['derived'].items()
                      if (derived or {}).get(name) == formula)
    return {'status': 'evaluated', 'evaluated': result['evaluated'], 'hits': hits,
            'hit_examples': strict_examples, 'predicate': check['predicate'],
            # The count the pre-r48 definition reported, kept as a comparison
            # reading under a name that cannot be mistaken for a hit.
            'predicate_only_hits': predicate_only,
            'derived_compared': compared,
            # How many points of the receipt's own grid satisfied the receipt's own
            # assertion. Reported next to `hits` so a reader can tell a hit on a
            # discriminating experiment (receipt_passed > 0) from one on an
            # experiment that failed everywhere (which the gate above refuses).
            'receipt_passed': receipt_passed,
            'hit_definition': HIT_DEFINITION, 'criteria_version': CRITERIA_VERSION}

def evaluate_point(check, point):
    """Score one named parameter point, e.g. the cleanest reported counterexample."""
    from .experiments import expression
    data = dict(point)
    for key, formula in check['derived'].items():
        data[key] = expression(formula, data, indicators=True)
    try:
        holds = expression(check['predicate'], data, assertion=True, indicators=True)
    except (ValueError, SyntaxError, ArithmeticError) as exc:
        return {'status': 'refused', 'reason': str(exc)}
    return {'status': 'evaluated', 'holds': bool(holds),
            'derived': {k: data[k] for k in check['derived']}, 'point': point}


def receipt_hits(knowledge, run, receipt_event, *, synthetic=False):
    """Downgrade proposals whose compiled falsifier is hit by this receipt.

    Only executed experiment receipts that actually found a counterexample can
    trigger anything: a passing sweep must never look like a refutation.
    """
    row = knowledge.db.execute('SELECT kind,payload,at FROM inquiry_events WHERE seq=?', (receipt_event,)).fetchone()
    if row is None or row[0] != 'tool_result':
        return {'status': 'skipped', 'reason': 'not a tool receipt'}
    # A hit is grounds for review only while its receipt still stands. The row
    # above is read straight from the event log, which keeps superseded bytes
    # forever, so without this a withdrawn observation could still downgrade a
    # proposal. Skipped, and deliberately not `not_hit`: nothing was scored.
    receipt_state = knowledge.dependencies.status(receipt_event)['state']
    if receipt_state != 'current_interpretation':
        return {'status': 'skipped',
                'reason': 'receipt is superseded' if receipt_state == 'superseded'
                          else 'receipt is ' + receipt_state}
    payload = json.loads(row[1])
    # When the receipt was observed. Every bridge product carries it forward:
    # a downgrade whose grounds cannot be dated is not reviewable months later.
    receipt_at = row[2]
    action = payload.get('action', {})
    result = payload.get('result')
    if payload.get('status') != 'executed' or action.get('kind') != 'experiment' or not isinstance(result, dict):
        return {'status': 'skipped', 'reason': 'not an executed experiment'}
    if not isinstance(result.get('counterexample_count'), int) or result['counterexample_count'] <= 0:
        return {'status': 'skipped', 'reason': 'receipt found no counterexample'}
    domain = result.get('domain')
    if not isinstance(domain, dict) or not domain:
        return {'status': 'skipped', 'reason': 'receipt did not record its searched domain'}
    outcomes = []
    rows = knowledge.db.execute("SELECT seq,payload FROM inquiry_events WHERE run=? AND kind='knowledge_proposal' ORDER BY seq", (run,)).fetchall()
    # Reported so an empty outcome is not mistaken for "no proposal was hit": in
    # the on-disk evidence DBs a receipt and the proposal citing it often live in
    # different runs, where this scan legitimately sees nothing.
    for event, raw in rows:
        data = json.loads(raw)
        if data.get('synthetic') and not synthetic:
            continue
        proposal = data.get('proposal') or {}
        check = proposal.get('falsifier_check')
        if check is None:
            continue
        state = knowledge.dependencies.status(event)['state']
        if state != 'current_interpretation':
            outcomes.append({'proposal': event, 'status': 'skipped', 'reason': 'proposal state is ' + state})
            continue
        # Re-derive the digest instead of trusting the stored field: prose may
        # have been edited after acceptance.
        try:
            current = compile_check(check, proposal.get('falsifier', ''))
        except ValueError as exc:
            outcomes.append({'proposal': event, 'status': 'refused', 'reason': str(exc)})
            continue
        # Pass the receipt's own derived formulas: without them a predicate can
        # silently be scored on a quantity the experiment never computed.
        # The assertion is what the experiment claimed and its own failure is what
        # makes a hit: without it the bridge can only say the predicate held.
        receipt_assertion = action.get('assertion')
        if not isinstance(receipt_assertion, str) and isinstance(result.get('assertion'), str):
            receipt_assertion = result['assertion']
        verdict = evaluate(current, domain, action.get('derived'), receipt_assertion)
        if verdict['status'] != 'evaluated':
            refused = {'proposal': event, 'status': 'refused', 'reason': verdict['reason'],
                       'detail': {'declared': verdict.get('declared'), 'receipt': verdict.get('receipt'),
                                  'differing': verdict.get('differing')}}
            # Only the r62 discrimination refusal carries this; older reasons do
            # not, and adding it unconditionally would restate old rows.
            if verdict.get('receipt_passed') == 0:
                refused['receipt_passed'] = 0
                refused['predicate_only_hits'] = verdict.get('hits')
            outcomes.append(refused)
            continue
        if verdict['hits'] <= 0:
            outcomes.append({'proposal': event, 'status': 'not_hit', 'evaluated': verdict['evaluated'],
                             'predicate_only_hits': verdict.get('predicate_only_hits'),
                             'criteria_version': verdict.get('criteria_version')})
            continue
        outcome = {'proposal': event, 'status': 'needs_review', 'receipt': receipt_event,
                   'receipt_at': receipt_at,
                   'predicate': current['predicate'], 'hits': verdict['hits'],
                   'evaluated': verdict['evaluated'], 'hit_examples': verdict['hit_examples'],
                   # The reviewer reads this payload, not the evaluate() call: without
                   # it here the coverage limit exists only one layer down and the hit
                   # text would read as if every derived formula had been compared.
                   'derived_compared': verdict.get('derived_compared'),
                   # The gate above compares the declared grid to the receipt's
                   # domain, but the reviewer only ever saw the hit point and a
                   # count. Without the receipt's own grid here, 'declared grid =
                   # receipt grid' can only be believed, not re-checked.
                   'domain': domain,
                   # r48 tightened what `hits` means. Old rows keep the old
                   # meaning, so a reader who compares counts across the two
                   # cannot tell which definition produced them unless this is
                   # stored with the reading itself.
                   'hit_definition': verdict.get('hit_definition'),
                   'criteria_version': verdict.get('criteria_version'),
                   'epistemic_status': 'finite_computation_under_stated_model_not_truth_verdict'}
        # r62: the receipt's own pass count, so 'the candidate was hit' can be
        # read against 'how discriminating was this experiment'. Omitted when the
        # reading did not produce it, so rows written before r62 keep their shape.
        if verdict.get('receipt_passed') is not None:
            outcome['receipt_passed'] = verdict['receipt_passed']
        # The cause must be this new hit event, not the receipt: status() drops a
        # cause that is the proposal's own ancestor, which would silently cancel
        # the downgrade whenever the proposal cites the very receipt that hit it.
        import datetime as _dt
        with knowledge.db:
            hit_event = knowledge.db.execute(
                'INSERT INTO inquiry_events(run,kind,payload,at) VALUES(?,?,?,?)',
                (run, 'falsifier_hit', json.dumps(outcome, ensure_ascii=False),
                 _dt.datetime.now(_dt.timezone.utc).isoformat())).lastrowid
            knowledge.db.execute('INSERT OR IGNORE INTO inquiry_review_queue(event,cause) VALUES(?,?)',
                                 (event, hit_event))
        outcome['hit_event'] = hit_event
        outcomes.append(outcome)
    return {'status': 'checked', 'receipt': receipt_event, 'receipt_at': receipt_at,
            'proposals_scanned': len(rows), 'outcomes': outcomes}
