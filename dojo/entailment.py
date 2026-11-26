"""Finite Boolean implication checks, never validation of a formalization."""
import ast
import itertools
import keyword
import re

from .experiments import expression


_NODES=(ast.Expression,ast.BoolOp,ast.And,ast.Or,ast.UnaryOp,ast.Not,
        ast.Compare,ast.Eq,ast.NotEq,ast.Name,ast.Load,ast.Constant)


class _Normalize(ast.NodeTransformer):
    def visit_Constant(self,node):
        return ast.copy_location(ast.Constant(int(node.value)),node)

    def visit_UnaryOp(self,node):
        # Every allowed operand is Boolean. Compile NOT to the already
        # verified numeric evaluator instead of adding another eval engine.
        return ast.copy_location(ast.Compare(left=self.visit(node.operand),ops=[ast.Eq()],comparators=[ast.Constant(0)]),node)


def _formula(text,names):
    if not isinstance(text,str) or not text.strip() or len(text)>160:
        raise ValueError('Boolean formula must contain 1..160 characters')
    try:tree=ast.parse(text.strip(),mode='eval')
    except (SyntaxError,ValueError,RecursionError):raise ValueError('invalid Boolean formula') from None
    nodes=list(ast.walk(tree))
    if len(nodes)>64:raise ValueError('Boolean formula is too complex')
    # Check the whole tree, including branches that would short-circuit.
    for node in nodes:
        if not isinstance(node,_NODES):raise ValueError('unsupported Boolean expression')
        if isinstance(node,ast.Name) and node.id not in names:raise ValueError('undeclared Boolean variable')
        if isinstance(node,ast.Constant) and not (type(node.value) is bool or type(node.value) is int and node.value in (0,1)):
            raise ValueError('only Boolean constants are allowed')
    normalized=ast.unparse(ast.fix_missing_locations(_Normalize().visit(tree)))
    if len(normalized)>300:raise ValueError('normalized Boolean formula is too long')
    return normalized


def _prepare(variables,premises,conclusion):
    if not isinstance(variables,dict) or len(variables)>8:raise ValueError('at most 8 Boolean variables are allowed')
    for name,meaning in variables.items():
        if not isinstance(name,str) or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}',name) is None or keyword.iskeyword(name):
            raise ValueError('invalid Boolean variable name')
        if not isinstance(meaning,str) or not meaning.strip() or len(meaning)>500:raise ValueError('variable meanings must be short nonempty text')
    if not isinstance(premises,list) or len(premises)>12:raise ValueError('at most 12 Boolean premises are allowed')
    names=sorted(variables)
    compiled=[_formula(p,names) for p in premises]
    target=_formula(conclusion,names)
    return names,compiled,target


def validate_action(action):
    if set(action)!={'kind','variables','premises','conclusion','assumptions','prediction'} or action['kind']!='check_entailment':
        raise ValueError('invalid entailment action fields')
    if not isinstance(action['assumptions'],list) or not 1<=len(action['assumptions'])<=12 or any(not isinstance(x,str) or not x.strip() or len(x)>2000 for x in action['assumptions']):
        raise ValueError('entailment formalization needs explicit assumptions')
    if not isinstance(action['prediction'],str) or not action['prediction'].strip() or len(action['prediction'])>2000:
        raise ValueError('entailment prediction is required')
    _prepare(action['variables'],action['premises'],action['conclusion'])


def check(variables,premises,conclusion):
    """Enumerate all assignments for <=8 declared Boolean variables.

    `variables` maps names to human-readable meanings, which are unverified
    input. Formulas use names, 0/1 or True/False, not/and/or and ==/!=. Empty
    premises permit tautology checks. Inconsistent premises are reported
    separately, never presented as usable evidence for an arbitrary claim.
    """
    names,compiled,target=_prepare(variables,premises,conclusion)
    supporting=[];counter=[];support_count=counter_count=0
    for values in itertools.product((0,1),repeat=len(names)):
        assignment=dict(zip(names,values))
        if not all(expression(p,assignment,assertion=True,indicators=True) for p in compiled):continue
        if expression(target,assignment,assertion=True,indicators=True):
            support_count+=1
            if len(supporting)<3:supporting.append(assignment)
        else:
            counter_count+=1
            if len(counter)<3:counter.append(assignment)
    total=support_count+counter_count
    status=('inconsistent_premises' if total==0 else
            'entailed' if counter_count==0 else
            'refuted' if support_count==0 else 'underdetermined')
    return dict(status=status,total_assignments=2**len(names),premise_model_count=total,
                supporting_model_count=support_count,countermodel_count=counter_count,
                entails_conclusion=None if total==0 else counter_count==0,
                entails_negation=None if total==0 else support_count==0,
                supporting_examples=supporting,countermodels=counter,
                supporting_examples_truncated=support_count>len(supporting),
                countermodels_truncated=counter_count>len(counter),
                arithmetic='Exhaustive Boolean assignments; no floating-point arithmetic.',
                scope='Only the supplied Boolean formalization is checked. Variable meanings, translation of reports, premise truth, completeness and real-world possibility are not verified. Countermodels are hypothetical assignments satisfying the formulas, not measured people or events. Inconsistent premises are not treated as usable proof.')
