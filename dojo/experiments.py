"""Finite, reproducible counterexample search under explicit model assumptions."""
import ast
import itertools
import json
import math
import operator
import re

OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.Pow:operator.pow}
COMPARISONS={ast.Lt:operator.lt,ast.LtE:operator.le,ast.Gt:operator.gt,ast.GtE:operator.ge,ast.Eq:operator.eq,ast.NotEq:operator.ne}
MAX_EXPRESSION_NODES=160

def validate_diagnosis(action):
    if set(action)!={'kind','source_event','equality_indices','absolute_tolerance','prediction'} or action['kind']!='diagnose_experiment':raise ValueError('invalid diagnosis fields')
    indices=action['equality_indices']
    if type(action['source_event']) is not int or not isinstance(indices,list) or not 1<=len(indices)<=8 or any(type(i) is not int or i<0 for i in indices) or len(set(indices))!=len(indices):raise ValueError('invalid diagnosis source/components')
    if numeric(action['absolute_tolerance'])<=0:raise ValueError('positive absolute tolerance required')
    if not isinstance(action['prediction'],str) or not action['prediction'].strip() or len(action['prediction'])>2000:raise ValueError('invalid prediction')

def diagnose(q,action):
    """Replay immutable inputs; only explicitly selected top-level equalities change."""
    validate_diagnosis(action)
    source=action['source_event']
    if source not in q.visible_source_text:raise ValueError('unseen experiment source')
    row=q.db.execute('SELECT kind,payload FROM inquiry_events WHERE seq=?',(source,)).fetchone()
    if row is None or row[0]!='tool_result':raise ValueError('not an experiment receipt')
    payload=json.loads(row[1]);original=payload.get('action',{})
    if payload.get('status')!='executed' or original.get('kind')!='experiment':raise ValueError('successful experiment required')
    if not q.synthetic and q.dependencies._synthetic(source):raise ValueError('source identity mismatch')
    if q.dependencies.status(source)['state']=='superseded':raise ValueError('superseded source')
    tree=ast.parse(original['assertion'],mode='eval').body
    parts=tree.values if isinstance(tree,ast.BoolOp) and isinstance(tree.op,ast.And) else [tree]
    selected=set(action['equality_indices']);changed=[]
    if max(selected)>=len(parts):raise ValueError('component outside assertion')
    for i,node in enumerate(parts):
        if i in selected:
            if not isinstance(node,ast.Compare) or len(node.ops)!=1 or not isinstance(node.ops[0],ast.Eq):raise ValueError('only single numeric equalities can be relaxed')
            changed.append('('+ast.unparse(node.left)+'-('+ast.unparse(node.comparators[0])+'))**2 <= '+repr(action['absolute_tolerance'])+'**2')
        else:changed.append('('+ast.unparse(node)+')')
    before=parameter_sweep(original['parameters'],original['derived'],original['assertion'])
    after=parameter_sweep(original['parameters'],original['derived'],' and '.join(changed))
    def observations(result):return {k:v for k,v in result.items() if k not in {'assertion','domain'}}
    return {'source_event':source,'original':observations(before),'tolerant':observations(after),
        'modified_equality_indices':sorted(selected),'unchanged_component_indices':[i for i in range(len(parts)) if i not in selected],
        'parameters_preserved':True,'derived_formulas_preserved':True,'unselected_conditions_preserved':True,
        'scope':'固定原模型和参数域的数值诊断；原始严格断言结果不变，容差不证明现实正确或精确恒等'}

def repair_hint(error):
    """Fixed interface help, never echo arbitrary exception or submitted code."""
    if isinstance(error,ZeroDivisionError):return '出现除零：检查分母及参数域，不把未定义点当通过。'
    if isinstance(error,ValueError) and str(error)=='派生量过多':return 'experiment最多8个派生量；把简单比较直接放进assertion，或复用已有中间量，不要加第9个派生量。原请求没有执行成功。'
    if isinstance(error,ValueError) and str(error)=='表达式过复杂':return '每个表达式最多160个AST节点、300字符；拆成较短中间量并按依赖顺序声明，总派生量仍不超过8。原请求没有执行成功。'
    if isinstance(error,(SyntaxError,ValueError)):
        return '只接受单个Python风格纯表达式：加减乘除和**乘方；^不是乘方。不接受for、print、sum、comb、列表或函数调用（含abs）。容差检查可写(a-b)**2 <= eps**2，仍须声明eps或用明确常数；不要为消除反例放松其他经济/逻辑条件。多组数值用experiment.parameters；二项分布小阶组合系数可先展开为常数。experiment派生式可将比较结果按0/1计数，如(a==1)+(b==1)；断言用比较和and/or。变量须先声明，派生量按给出顺序计算；幂指数绝对值最多12。'
    return '数值运算失败；缩小数值/指数范围并检查定义域，未执行成功不能作为验证。'


def numeric(value):
    if type(value) not in (int,float) or abs(value)>1e15 or not math.isfinite(value):
        raise ValueError('数值超出有限包络')
    return value


def expression(text, variables=None, *, assertion=False, indicators=False):
    if not isinstance(text,str) or len(text)>300:raise ValueError('表达式过长')
    tree=ast.parse(text,mode='eval')
    if len(list(ast.walk(tree)))>MAX_EXPRESSION_NODES:raise ValueError('表达式过复杂')
    variables=variables or {}
    def computed_number(value):
        # Only evaluated comparisons may become 0/1. Constants and supplied
        # variables still pass numeric(), which rejects bool input values.
        return int(value) if indicators and type(value) is bool else numeric(value)
    def walk(node):
        if isinstance(node,ast.Constant):return numeric(node.value)
        if isinstance(node,ast.Name) and node.id in variables:return numeric(variables[node.id])
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
            return numeric(computed_number(walk(node.operand))*(-1 if isinstance(node.op,ast.USub) else 1))
        if isinstance(node,ast.BinOp) and type(node.op) in OPS:
            a,b=computed_number(walk(node.left)),computed_number(walk(node.right))
            if isinstance(node.op,ast.Pow) and abs(b)>12:raise ValueError('指数超出范围')
            return numeric(OPS[type(node.op)](a,b))
        if (assertion or indicators) and isinstance(node,ast.Compare):
            left=computed_number(walk(node.left))
            for op,right in zip(node.ops,node.comparators):
                if type(op) not in COMPARISONS:raise ValueError('不支持的比较')
                right=computed_number(walk(right))
                if not COMPARISONS[type(op)](left,right):return False
                left=right
            return True
        if (assertion or indicators) and isinstance(node,ast.BoolOp) and isinstance(node.op,(ast.And,ast.Or)):
            values=[walk(x) for x in node.values]
            if indicators:values=[bool(x) if type(x) in (int,float) and x in (0,1) else x for x in values]
            if any(type(x) is not bool for x in values):raise ValueError('断言必须是布尔比较')
            return all(values) if isinstance(node.op,ast.And) else any(values)
        raise ValueError('仅支持纯数值表达式及声明变量')
    result=walk(tree.body)
    if assertion and indicators and type(result) in (int,float) and result in (0,1):result=bool(result)
    if assertion and type(result) is not bool:raise ValueError('断言必须是布尔比较')
    if not assertion:result=computed_number(result)
    return result


def parameter_sweep(parameters, derived, assertion):
    if not isinstance(parameters,dict) or not 1<=len(parameters)<=5:raise ValueError('参数数量须为1至5')
    if not isinstance(derived,dict) or len(derived)>8:raise ValueError('派生量过多')
    names=list(parameters)+list(derived)
    if len(set(names))!=len(names) or any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}',name) for name in names):
        raise ValueError('变量名不合法或重复')
    count=1
    for values in parameters.values():
        if not isinstance(values,list) or not 1<=len(values)<=20:raise ValueError('每个参数须为1至20个值')
        for value in values:numeric(value)
        if len(set(values))!=len(values):raise ValueError('重复参数值不构成新观察')
        count*=len(values)
    if count>10000:raise ValueError('参数组合超出10000个')
    if not isinstance(assertion,str) or len(assertion)>300:raise ValueError('表达式过长')
    tree=ast.parse(assertion,mode='eval').body
    parts=[ast.unparse(node) for node in tree.values] if isinstance(tree,ast.BoolOp) and isinstance(tree.op,ast.And) else [assertion]
    comparisons=[ast.parse(part,mode='eval').body for part in parts]
    components=[{'index':i,'evaluated':count,'passed':0,'counterexample_count':0,'counterexample_parameters':[],'failed_numeric_comparisons':[]} for i in range(len(parts))]
    failures=[];successes=[];samples=[];passed=0;ranges={key:[None,None] for key in derived}
    binary_counts={key:{'zero':0,'one':0} for key in derived}
    for values in itertools.product(*parameters.values()):
        point=dict(zip(parameters,values));data=dict(point)
        for key,formula in derived.items():
            value=expression(formula,data,indicators=True);data[key]=value
            if key in binary_counts:
                if value in (0,1):binary_counts[key]['one' if value==1 else 'zero']+=1
                else:del binary_counts[key]
            lo,hi=ranges[key]
            ranges[key]=[value if lo is None else min(lo,value),value if hi is None else max(hi,value)]
        holds=expression(assertion,data,assertion=True,indicators=True)
        for component,part,node in zip(components,parts,comparisons):
            if expression(part,data,assertion=True,indicators=True):component['passed']+=1
            else:
                component['counterexample_count']+=1
                if len(component['counterexample_parameters'])<2:
                    component['counterexample_parameters'].append(point)
                    if isinstance(node,ast.Compare) and len(node.ops)==1:
                        left=expression(ast.get_source_segment(part,node.left),data,indicators=True)
                        right=expression(ast.get_source_segment(part,node.comparators[0]),data,indicators=True)
                        component['failed_numeric_comparisons'].append({'parameters':point,'left_value':left,'right_value':right,'difference':left-right})
        if len(samples)<10:samples.append({'parameters':point,'derived':{k:data[k] for k in derived},'assertion_holds':holds})
        if holds:
            passed+=1
            if len(successes)<10:successes.append({'parameters':point,'derived':{k:data[k] for k in derived}})
        elif len(failures)<10:failures.append({'parameters':point,'derived':{k:data[k] for k in derived}})
    for component in components:component['counterexample_parameters_truncated']=component['counterexample_count']>len(component['counterexample_parameters'])
    return {'evaluated':count,'passed':passed,'counterexample_count':count-passed,'counterexamples':failures,'component_checks':components,
        'passing_examples':successes,'passing_examples_truncated':passed>len(successes),
        'derived_ranges':ranges,'binary_derived_counts':binary_counts,
        'assertion_scope':'assertion and every derived value are evaluated separately at each parameter point; binary_derived_counts aggregates all grid points only for derived quantities whose values are always 0 or 1. Aggregate counts are not expression variables. Failed point assertions do not refute separate claims about aggregate counts.',
        'sample_points':samples,'sample_points_truncated':count>len(samples),'assertion':assertion,'domain':parameters,
        'numerical_mode':'Python整数及浮点运算；浮点临界值不构成精确数学证明',
        'scope':'确定性枚举；仅检验给定模型与参数域，不是现实实测或域外证明'}
