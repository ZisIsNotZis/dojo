"""Exact, bounded identifiability certificates for explicitly supplied linear models.

X beta are predictions and c beta is the desired contrast. This does not infer
X, c, independence, exchangeability or a causal model from natural language.
"""
from fractions import Fraction
import math


def _number(value):
    if type(value) not in (int,float) or abs(value)>10000 or not math.isfinite(value):
        raise ValueError('design entries must be finite bounded numbers')
    value=Fraction(str(value))
    if value.denominator>1000000:raise ValueError('design entry precision exceeds bound')
    return value


def validate_action(action):
    if not isinstance(action,dict) or set(action)!={'kind','terms','rows','contrast','assumptions','prediction'} or action['kind']!='check_design':raise ValueError('invalid design fields')
    terms=action['terms'];rows=action['rows'];contrast=action['contrast']
    if not isinstance(terms,list) or not 1<=len(terms)<=8 or any(not isinstance(t,str) or not t.strip() or len(t)>80 for t in terms) or len(set(terms))!=len(terms):raise ValueError('invalid design terms')
    if not isinstance(rows,list) or not 1<=len(rows)<=32 or any(not isinstance(row,list) or len(row)!=len(terms) for row in rows):raise ValueError('invalid design rows')
    if not isinstance(contrast,list) or len(contrast)!=len(terms):raise ValueError('invalid design contrast')
    for row in rows:
        for value in row:_number(value)
    parsed_contrast=[_number(value) for value in contrast]
    if not any(parsed_contrast):raise ValueError('design contrast must be nonzero')
    if not isinstance(action['assumptions'],list) or not 1<=len(action['assumptions'])<=12 or any(not isinstance(a,str) or not a.strip() or len(a)>2000 for a in action['assumptions']):raise ValueError('invalid design assumptions')
    if not isinstance(action['prediction'],str) or not action['prediction'].strip() or len(action['prediction'])>2000:raise ValueError('invalid design prediction')


def _rref(rows):
    rows=[list(row) for row in rows];pivots=[];next_row=0
    for column in range(len(rows[0])):
        found=next((r for r in range(next_row,len(rows)) if rows[r][column]),None)
        if found is None:continue
        rows[next_row],rows[found]=rows[found],rows[next_row]
        divisor=rows[next_row][column];rows[next_row]=[v/divisor for v in rows[next_row]]
        for r in range(len(rows)):
            if r==next_row:continue
            factor=rows[r][column]
            rows[r]=[v-factor*p for v,p in zip(rows[r],rows[next_row])]
        pivots.append(column);next_row+=1
        if next_row==len(rows):break
    return rows,pivots


def check(action):
    validate_action(action)
    rows=[[_number(v) for v in row] for row in action['rows']]
    contrast=[_number(v) for v in action['contrast']]
    reduced,pivots=_rref(rows);columns=len(contrast)
    result={'row_count':len(rows),'column_count':columns,'rank':len(pivots),
        'arithmetic':'exact rational; vectors encoded as integer or numerator/denominator strings',
        'scope':'Only identifiability of c*beta from predictions X*beta in the supplied exact linear model. No outcomes observed; no noise, causal validity, correct feature encoding, independent units or real-world generalization certified.'}
    for free in range(columns):
        if free in pivots:continue
        witness=[Fraction(0)]*columns;witness[free]=Fraction(1)
        for r,pivot in enumerate(pivots):witness[pivot]=-reduced[r][free]
        shift=sum(c*v for c,v in zip(contrast,witness))
        if not shift:continue
        witness=[v/shift for v in witness]
        changes=[sum(v*b for v,b in zip(row,witness)) for row in rows]
        result.update(identifiable=False,coefficient_shift=[str(v) for v in witness],prediction_changes=[str(v) for v in changes],contrast_change=str(sum(c*v for c,v in zip(contrast,witness))))
        return result
    # c is in the row span of X. Find an explicit w such that X^T w = c;
    # then c*beta = w*(X*beta). Coefficients not constrained by c may remain free.
    equations=[[row[j] for row in rows]+[contrast[j]] for j in range(columns)]
    solved,weight_pivots=_rref(equations);weights=[Fraction(0)]*len(rows)
    for r,pivot in enumerate(weight_pivots):
        if pivot>=len(rows):raise ArithmeticError('inconsistent row-space certificate')
        weights[pivot]=solved[r][-1]
    reconstructed=[sum(w*row[j] for w,row in zip(weights,rows)) for j in range(columns)]
    if reconstructed!=contrast:raise ArithmeticError('invalid row-space certificate')
    result.update(identifiable=True,observation_weights=[str(w) for w in weights],reconstructed_contrast=[str(v) for v in reconstructed])
    return result
