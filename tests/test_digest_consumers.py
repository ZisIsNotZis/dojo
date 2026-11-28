"""What a digest can and cannot license, pinned at the consumer boundary.

r38 produced a counterexample: a candidate whose `falsifier_sha256` equals
`sha256(prose)` while the predicate says something the prose does not
(`net>1000` against "if setup exceeds 48 minutes"). That is not a hole in the
gate. The digest is byte identity over the prose, so all it can prove is "this
predicate was submitted together with this prose" -- never "this predicate
expresses this prose".

This module pins that limit where it could become dangerous: the readers. Every
digest comparison in `dojo/` is enumerated from source and must appear in
`AUDITED` with a classification. The list is the claim that no consumer needs
semantic agreement, so adding a reader that does requires editing this file on
purpose.
"""
import ast
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from dojo.experiments import parameter_sweep
from dojo.falsifier import compile_check
from dojo.inquiry import Inquiry
from tests.test_knowledge import Client

REPO = Path(__file__).resolve().parent.parent

# kind: why this line cannot be misled by a digest that only proves byte identity.
#   'same-bytes'  -- asks "were these the same bytes" (tamper / staleness / dedupe)
#   'exclusion'   -- not a comparison at all: drops the key when hashing a body
AUDITED = {
    ('anchors.py', "body={k:v for k,v in packet.items() if k!='sha256'}"): 'exclusion',
    ('anchors.py', "if source['dependency_status']['state']!='current_interpretation' or self.source_hash(source)!=entry['source_hash']:raise ValueError('frontend anchor changed')"): 'same-bytes',
    ('associations.py', "if current is None or current['sha256']!=original['sha256']:"): 'same-bytes',
    ('associations.py', "if data['sha256'] in (previous['packet_sha256'],previous.get('result_packet_sha256')) and (kind=='question_associations' or not retry_failed):return {'requests_used':0,'status':'unchanged'}"): 'same-bytes',
    ('delivery_edits.py', "if digest(shown)!=shown.get('sha256') or shown['draft']!=original:raise ValueError('edit packet changed')"): 'same-bytes',
    ('delivery_edits.py', "return hashlib.sha256(json.dumps({k:v for k,v in value.items() if k!='sha256'},ensure_ascii=False,sort_keys=True).encode()).hexdigest()"): 'exclusion',
    ('deterministic.py', "if data['policy']==POLICY:attempted.add((data['target'],data['packet_sha256']))"): 'same-bytes',
    # r39 missed this one: membership against a bare name, not a bracket.
    ('deterministic.py', "if (event,digest) in attempted:continue"): 'same-bytes',
    ('falsifier.py', "if 'falsifier_sha256' in check and check['falsifier_sha256'] != digest:"): 'same-bytes',
    ('inquiry.py', "if digest==self.last_distillation_hash:return {'status':'unchanged'}"): 'same-bytes',
    ('inquiry.py', "if self.sent_source_hashes.get(event)==digest:continue"): 'same-bytes',
    # r87 replaced the digest-set membership test with a two-part question: does the
    # stored digest match, and if not, is there newer review work on this packet?
    # Both halves still ask 'were these the same bytes / is there new work', never
    # 'does this text mean that text'. The r87 pair is listed where it now lives.
    ('knowledge.py', 'matches=stored_digest==digest'): 'same-bytes',
    ('knowledge.py', "if stored_digest==packet['sha256'] or not _reopened_since(self.db,event,seq):"): 'same-bytes',
    # r63: the attempt record is keyed by the packet digest. Byte identity is the
    # whole question -- an attempt on other content is not this packet's history.
    ('question_reviews.py', "if (packet['target'],packet['sha256']) not in attempted:yield packet"): 'same-bytes',
    ('question_reviews.py', "if origins!=review_origin_view(q,packet) and review_packet(q,packet['target'])['sha256']==packet['sha256']:"): 'same-bytes',
    ('question_reviews.py', "if packet_hash(packet)!=packet['sha256'] or review_packet(q,packet['target'])['sha256']!=packet['sha256']:"): 'same-bytes',
    ('research.py', "data={k:v for k,v in data.items() if k not in {'sha256','existing_links'}}"): 'exclusion',
    ('research.py', "if current is None or current['sha256']!=original['sha256']:"): 'same-bytes',
    ('research.py', "if prior.get('status')!='deferred' and prior['packet_sha256']==original['sha256']:return {'status':'unchanged','requests_used':0}"): 'same-bytes',
    ('research.py', "if prior.get('status')!='deferred' or prior.get('material_sha256',prior.get('packet_sha256'))!=material_hash:continue"): 'same-bytes',
    ('reviews.py', "if origins!=review_origin_view(q,packet) and q.knowledge.review_packet(packet['target'])['sha256']==packet['sha256']:"): 'same-bytes',
    ('reviews.py', "if packet_hash(packet)!=packet['sha256'] or inquiry.knowledge.review_packet(packet['target'])['sha256']!=packet['sha256']:"): 'same-bytes',
    # r112c: an acceptance event names the wording it was accepted for, and retrieval
    # compares that to the card's current wording. Byte identity is exactly the
    # question: "is the wording on screen the same bytes the user accepted?". It is
    # not asking whether a rewrite means the same thing -- it fails closed when the
    # bytes differ, which is the point (#1497).
    ('storage.py', 'if digest and digest == wanted:'): 'same-bytes',
    # r112d: the read-only report asks the same byte-identity question per card, to
    # print "accepted wording is the current one" rather than infer it. No semantics.
    ('storage.py', 'if any(digest == wanted for digest in digests):'): 'same-bytes',
    # A pasted locator accepts only the trace bytes it was generated against.
    ('transcript.py', 'if len(data) > MAX_TRACE_BYTES or sha256(data).hexdigest() != expected_sha256:'): 'same-bytes',
}

PROSE = '若第二人每天要复核的件数超过其容量，则流量并未真正转移。'
PARAMS = {'N': [20, 50], 'u': [5, 60], 'C': [2, 40]}
DERIVED = {'to_second': 'N*u/100'}
# Keyed to the prose by digest, yet semantically unrelated to it: the prose is
# about capacity, the predicate asks whether a derived value exceeds 1000.
UNRELATED = {'falsifier_sha256': hashlib.sha256(PROSE.encode('utf-8')).hexdigest(),
             'parameters': PARAMS, 'derived': DERIVED, 'predicate': 'to_second>1000',
             'predicate_fails_at': {'N': 20, 'u': 5, 'C': 40}}

TOKEN = re.compile(r'(sha256|source_hash|material_hash|\bdigest\b|packet_hash)')
# `in` counts as membership when followed by a bracket or a plain name.
# r39 required a bracket, to keep the English word "in" out of prose -- but that
# also hid `if (event,digest) in attempted`, and would have blessed a semantic
# reader written as `if digest in certified_meanings`. English-word noise is
# already handled: no comment/docstring-leading line, and a digest token must
# also appear on the line.
OP = re.compile(r'(==|!=|\bnot\s+in\b|\bin\s+[\[({A-Za-z_])')
# A `for x in y` header is not a membership test on the loop target.
FOR_CLAUSE = re.compile(r'\bfor\s+[^:]*?\bin\b')


def digest_comparisons(text):
    """Every line that compares, or membership-tests, a digest value."""
    found = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(('#', '"""', "'''")):
            continue
        code = line.split('#')[0]
        probe = FOR_CLAUSE.sub(' for ', code)
        if TOKEN.search(code) and OP.search(probe):
            found.add((re.sub(r'\s+', ' ', code.strip())))
    return found


def payload_rewrites(text):
    """Statements that could edit an already-stored event in place."""
    return [line.strip() for line in text.splitlines()
            if re.search(r'UPDATE\s+inquiry_events\s+SET', line, re.I)]


def scan(folder):
    seen = {}
    for path in sorted(Path(folder).glob('*.py')):
        for line in digest_comparisons(path.read_text(encoding='utf-8')):
            seen[(path.name, line)] = None
    return seen


DOMAINS = ('dojo', 'scripts', 'tests')
# Where the bridge key may legitimately be named: the three production files that
# define and read it, and the three tests that exercise it. r41 measured this with
# throwaway probes; pinned here so a new mention has to be added on purpose.
BRIDGE_KEY_FILES = {'dojo/falsifier.py', 'dojo/inquiry.py', 'dojo/knowledge.py',
                    'tests/test_digest_consumers.py', 'tests/test_falsifier_bridge.py',
                    'tests/test_provenance_time.py', 'tests/test_review_attempts.py'}

# r41 reported this as "2 Compare nodes, both at falsifier.py:41". Half of that was
# wrong: the `in check` half tests a key name, not a digest value. After separating
# the two, the honest figure is **one comparison site**, and it is this audit's own
# exclusion list that keeps it at one rather than two-people-got-lucky.


def sources_of(folders=DOMAINS):
    """{relative name: source text} for every module in the given folders."""
    return {f'{folder}/{path.name}': path.read_text(encoding='utf-8', errors='replace')
            for folder in folders
            for path in sorted((REPO / folder).glob('*.py'))}


def mentioning_bridge_key(sources):
    """Files that name `falsifier_check` anywhere: code, string, or docstring.

    Deliberately textual rather than AST. The question is whether anyone reads
    the key; a read spelled `data['falsifier' + '_check']` is still a read, and a
    test that only looked at attribute/subscript nodes would miss it.
    """
    return {name for name, text in sources.items() if 'falsifier_check' in text}


def _reads_falsifier_digest(node):
    """True if this expression *reads a digest value*, not merely its name.

    The distinction matters and r41 elided it. `'falsifier_sha256' in check`
    tests a key name; `check['falsifier_sha256'] != digest` compares a value.
    Only the second could ever be misled by a digest whose bytes match text it
    does not describe, so only the second is what this audit is about. Keying on
    the bare string would also flag any code that merely spells the field name --
    including this module's own scanner.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant) \
                and sub.slice.value == 'falsifier_sha256':
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == 'falsifier_sha256':
            return True
        if isinstance(sub, ast.Name) and sub.id == 'falsifier_sha256':
            return True
    return False


def falsifier_digest_comparisons(sources):
    """{file: [Compare nodes]} whose either side mentions `falsifier_sha256`.

    r38's counterexample lives at this boundary: a candidate may carry a digest
    that matches the prose while the predicate says something the prose does not.
    That is bearable only because the digest is compared nowhere except against
    itself. A second comparison site would be someone deciding it means more.
    """
    found = {}
    for name, text in sources.items():
        for node in ast.walk(ast.parse(text.lstrip('\ufeff'))):
            if not isinstance(node, ast.Compare):
                continue
            if _reads_falsifier_digest(node.left) \
                    or any(_reads_falsifier_digest(c) for c in node.comparators):
                found.setdefault(name, []).append(node)
    return found


def enclosing_functions(tree):
    """{lineno: dotted function name} so an assertion can name code, not lines."""
    spans = {}

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                for number in range(child.lineno, (child.end_lineno or child.lineno) + 1):
                    spans[number] = name
                walk(child, name + '.')
            else:
                walk(child, prefix)

    walk(tree, '')
    return spans


class DigestIsByteIdentity(unittest.TestCase):
    def test_the_digest_separates_bytes_not_meanings(self):
        """Same meaning, other bytes, other digest. Nothing here reads text."""
        same_meaning = PROSE.replace('，', ',')
        self.assertNotEqual(hashlib.sha256(PROSE.encode('utf-8')).hexdigest(),
                            hashlib.sha256(same_meaning.encode('utf-8')).hexdigest())

    def test_a_predicate_the_prose_does_not_say_passes_the_gate(self):
        """The r38 counterexample, pinned as expected behaviour.

        The gate checks that the predicate travels with this prose, not that it
        expresses it. Pinned so nobody turns the digest into a semantic check it
        cannot be, and so nobody reads a passing gate as text/formula agreement.
        """
        check = compile_check(UNRELATED, PROSE)
        self.assertEqual(hashlib.sha256(PROSE.encode('utf-8')).hexdigest(), check['falsifier_sha256'])


class NoConsumerNeedsSemantics(unittest.TestCase):
    def test_every_digest_comparison_in_dojo_is_audited(self):
        """The allowlist is the claim: all readers want byte identity."""
        seen = scan(REPO / 'dojo')
        self.assertEqual(set(AUDITED), set(seen))

    def test_every_audited_reader_is_byte_identity_not_semantics(self):
        """No reader is allowed to be filed under a semantic category.

        The two kinds here are the only admissible answers. A line that needed
        'the hashed text means what the other text means' would have to introduce
        a third kind, and this assertion is what makes that a deliberate act.
        """
        self.assertEqual({'same-bytes', 'exclusion'}, set(AUDITED.values()))

    def test_the_audit_reports_a_new_unlisted_comparison(self):
        """Teeth: a reader added tomorrow must not pass silently."""
        planted = "return p['sha256'] == q['sha256'] and p['truth'] == 'certified'"
        found = digest_comparisons('def gate(p, q):\n    ' + planted + '\n')
        self.assertIn(planted, found)
        self.assertNotIn(('knowledge.py', planted), AUDITED)

    def test_the_audit_sees_comparisons_that_do_not_spell_sha256(self):
        """A digest compared through a helper name must not escape the scan.

        Four real readers compare `source_hash(...)` or a local `digest`; a scan
        keyed only on the literal 'sha256' would have reported a clean bill of
        health while missing them.
        """
        for planted in ("if self.source_hash(source) != entry['source_hash']: raise ValueError('x')",
                        'if digest == self.last_distillation_hash: return None'):
            with self.subTest(planted=planted):
                self.assertTrue(digest_comparisons(planted + '\n'))

    def test_the_audit_sees_membership_against_a_bare_name(self):
        """A dedupe/membership test on a plain name must not escape the scan.

        r39 counted `in` only when followed by a bracket, so the English word
        "in" in prose could not be mistaken for an operator. The cost was
        invisible membership tests: `if (event,digest) in attempted` and, worse,
        `if digest in certified_meanings` -- a semantic reader would have been
        blessed by silence. This tooth fails on the r39 scanner.
        """
        for planted in ('if (event,digest) in attempted:continue',
                        'if digest in certified_meanings:return True'):
            with self.subTest(planted=planted):
                self.assertTrue(digest_comparisons(planted + '\n'))

    def test_a_for_clause_is_not_a_comparison(self):
        """The widening must not count `for x in y` as a membership test."""
        loop = ("attempted={json.loads(row[0]).get('packet_sha256') "
                "for row in self.db.execute('SELECT payload')}")
        self.assertFalse(digest_comparisons(loop + '\n'))

    def test_no_production_code_rewrites_a_stored_event_payload(self):
        """Why a digest can describe what was reviewed.

        Events are append-only: no writer edits a payload after it is stored, so
        a digest computed at write time still describes the bytes read back. If
        that changes, the digest stops being evidence of anything.
        """
        offenders = []
        for path in sorted((REPO / 'dojo').glob('*.py')):
            offenders.extend(f'{path.name}: {line}'
                             for line in payload_rewrites(path.read_text(encoding='utf-8')))
        self.assertEqual([], offenders)

    def test_the_rewrite_scan_catches_a_planted_statement(self):
        """Teeth for the append-only claim above."""
        planted = "db.execute('UPDATE inquiry_events SET payload=? WHERE seq=?', (x, y))"
        self.assertEqual([planted], payload_rewrites(planted + '\n'))


class TheLimitHoldsOutsideDojo(unittest.TestCase):
    """r40 said 'no consumer needs semantics' but had only enumerated `dojo/`.

    r41 widened the domain to `dojo/` + `scripts/` + `tests/` (37 + 136 + 69 files)
    and the claim survived -- for a stronger reason than expected: outside dojo/
    there is no reader at all, not merely no semantic reader. That reading came
    from throwaway probes. These two assertions are what keeps it true, and they
    fail on a new consumer rather than on new prose.
    """

    def test_only_known_files_name_the_bridge_key(self):
        """Across all three folders, exactly six files mention `falsifier_check`.

        Three define or read it (`falsifier.py`, `inquiry.py`, `knowledge.py`);
        three test it. Zero in `scripts/`: the 136 audit and probe scripts do not
        touch the bridge. A seventh file is either a new consumer that skipped
        review or a rename -- both worth failing on.
        """
        self.assertEqual(BRIDGE_KEY_FILES, mentioning_bridge_key(sources_of()))

    def test_the_bridge_key_scan_catches_a_new_reader_in_scripts(self):
        """Teeth: a reader added under scripts/ must not pass silently."""
        planted = {'scripts/probe_new.py': "check=data['falsifier_check']\n"}
        self.assertEqual({'scripts/probe_new.py'}, mentioning_bridge_key(planted))
        self.assertFalse(mentioning_bridge_key(planted) <= BRIDGE_KEY_FILES)

    def test_the_falsifier_digest_is_compared_in_exactly_one_function(self):
        """One comparison site in the whole repo, and it compares bytes.

        `falsifier.py:41` refuses a check whose stated digest differs from the
        prose's. Nothing else compares this digest to anything. r38 showed the
        digest does not establish that the predicate expresses the prose; that
        stays harmless only while no second site treats it as if it did.
        """
        sources = sources_of()
        found = falsifier_digest_comparisons(sources)
        sites = {}
        for name, nodes in found.items():
            spans = enclosing_functions(ast.parse(sources[name].lstrip('\ufeff')))
            sites[name] = {spans.get(node.lineno, '<module>') for node in nodes}
        self.assertEqual({'dojo/falsifier.py': {'compile_check'}}, sites)

    def test_the_digest_comparison_scan_catches_a_second_site(self):
        """Teeth: a semantic consumer of the digest must be visible to the scan."""
        planted = {'scripts/verify.py':
                   "def certify(check, prose):\n"
                   "    return check['falsifier_sha256'] == hashlib.sha256(prose.encode()).hexdigest()\n"}
        self.assertEqual({'scripts/verify.py'}, set(falsifier_digest_comparisons(planted)))

    def test_naming_the_key_is_not_the_same_as_reading_the_digest(self):
        """A presence check on the field name is not a digest comparison.

        `compile_check` has both in one condition: `'falsifier_sha256' in check`
        (is a digest stated at all?) and `check['falsifier_sha256'] != digest`
        (is it the right one?). Only the second is the byte guarantee this audit
        covers. Counting both would have inflated r41's figure to 2 and, worse,
        would flag any future code that merely spells the field name.
        """
        one = "if 'falsifier_sha256' in check and check['falsifier_sha256'] != digest:\n    raise ValueError('x')\n"
        nodes = falsifier_digest_comparisons({'dojo/falsifier.py': one})['dojo/falsifier.py']
        self.assertEqual(1, len(nodes))
        self.assertIn("check['falsifier_sha256'] != digest", ast.unparse(nodes[0]))

    def test_a_presence_check_alone_is_not_a_comparison_site(self):
        """Teeth for the split above, in the direction that would over-report."""
        only_name = "if 'falsifier_sha256' in check:\n    pass\n"
        self.assertEqual({}, falsifier_digest_comparisons({'x.py': only_name}))


class BridgeKeysAreReadOnly(unittest.TestCase):
    def test_no_code_branches_on_the_bridge_keys(self):
        """The two bridge keys are written into packets and never tested.

        They inform a reader; they decide nothing. If a future line were to test
        for their presence, a missing key would start meaning 'not scored' to the
        code rather than to the reader -- which is exactly the laundering r37's
        wording was written to avoid.
        """
        # A read is the key looked up in a packet inside a branch. The two
        # construction sites assign to locals named `bridge` / `checked_without_hit`,
        # so they record the reading; they do not decide anything from it.
        branch = re.compile(r'(if|elif|while|assert)\b')
        lookup = re.compile(r"(\['bridge(_checked_without_hit)?'\]|\.get\('bridge(_checked_without_hit)?')")
        offenders = []
        for path in sorted((REPO / 'dojo').glob('*.py')):
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                code = line.split('#')[0]
                # Blank out assignment targets: `packet['bridge']=bridge` records a
                # reading, it does not consume one.
                candidate = re.sub(r"\['bridge(_checked_without_hit)?'\]\s*=", " ", code)
                if branch.search(candidate) and lookup.search(candidate):
                    offenders.append(f'{path.name}:{number}: {code.strip()}')
        self.assertEqual([], offenders)


class BridgeKeysOnOnePacket(unittest.TestCase):
    """Both bridge keys can coexist -- but only by editing a stored event."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.q = Inquiry(Path(self.tmp.name) / 'db', Client(), synthetic=True)
        self.u = self.q.record('user', {'text': '没人再问我了', 'synthetic': True})

    def tearDown(self):
        self.q.close()
        self.tmp.cleanup()

    def accept(self, predicate):
        p = {'statement': '未归类比例把第二个人变成瓶颈时，流量没有真正转移。', 'kind': 'causal',
             'method': 'hypothesis', 'premises': [{'event': self.u, 'quote': '没人再问我了', 'role': 'assumption'}],
             'assumptions': ['容量固定'], 'conditions': ['仅此参数网格'], 'alternatives': ['保留兵底'],
             'falsifier': PROSE, 'revises': None,
             'falsifier_check': {'falsifier_sha256': hashlib.sha256(PROSE.encode('utf-8')).hexdigest(),
                                 'parameters': PARAMS, 'derived': DERIVED, 'predicate': predicate,
                                 'predicate_fails_at': {'N': 20, 'u': 5, 'C': 40}}}
        return self.q.knowledge.accept(self.q.run, p, {self.u}, synthetic=True)

    def experiment(self):
        """The real entry: only execute_action records bridge_checked."""
        action = {'kind': 'experiment', 'parameters': PARAMS, 'derived': DERIVED,
                  'assertion': 'to_second<=C', 'assumptions': ['容量固定'], 'prediction': 'p'}
        reflection = self.q.record('reflection', {'synthetic': True,
                                                  'reflection': {'answer': '测一下', 'action': action}})
        return self.q.execute_action(action, reflection)[0]

    def test_the_two_bridge_keys_coexist_only_behind_a_payload_rewrite(self):
        """A hit and a miss can land on one packet if a stored check is edited.

        Constructed here on purpose: `falsifier_sha256` is not recomputed against
        the prose, so rewriting the stored predicate to one the prose does not
        state keeps the digest valid, and a second pass can then post the
        opposite reading beside the first. Production never reaches this: the
        scan above proves `dojo/` holds no statement that edits a stored event.
        Pinned so the invariant is visible, and so the day someone adds such a
        writer this test is the reminder that the two keys need an exclusion rule.
        """
        # Miss first: a hit moves the proposal to needs_review, and the bridge
        # only scores proposals still sitting at current_interpretation.
        claim = self.accept('to_second>1000')
        self.experiment()
        checked = json.loads(self.q.db.execute(
            "SELECT payload FROM inquiry_events WHERE kind='falsifier_bridge_checked' "
            'ORDER BY seq DESC LIMIT 1').fetchone()[0])
        self.assertEqual([{'proposal': claim, 'status': 'not_hit', 'evaluated': 8,
                           'predicate_only_hits': 0, 'criteria_version': 'r48'}], checked['outcomes'])
        self.assertNotIn('bridge', self.q.knowledge.review_packet(claim))

        row = self.q.db.execute('SELECT payload FROM inquiry_events WHERE seq=?', (claim,)).fetchone()[0]
        data = json.loads(row)
        data['proposal']['falsifier_check']['predicate'] = 'to_second>C'
        self.q.db.execute('UPDATE inquiry_events SET payload=? WHERE seq=?',
                          (json.dumps(data, ensure_ascii=False), claim))
        self.q.db.commit()

        self.experiment()
        self.assertEqual('needs_review', self.q.dependencies.status(claim)['state'])
        packet = self.q.knowledge.review_packet(claim)
        self.assertIn('bridge', packet)
        self.assertIn('bridge_checked_without_hit', packet)


if __name__ == '__main__':
    unittest.main()
