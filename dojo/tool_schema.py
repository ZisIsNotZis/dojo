"""Native function schemas guide generation; runtime validators remain authoritative."""

def function(name,description,properties):
 return {'type':'function','function':{'name':name,'description':description,
  'parameters':{'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}}}

TEXT={'type':'string'}
DETERMINISTIC_TOOLS=frozenset({'calculate','experiment','diagnose_experiment','check_design','check_entailment','check_progress'})
HOST_TOOLS=[
 function('check_progress','检查有限状态转换图中，从initial出发的每条极大路径是否最终首次到达goals，而不只是存在一条成功路径。states为最多32个短ID到含义的映射；transitions最多128条，source/target必须是已声明ID。可能无限等待应建非目标自环；不能把需要人回应的步骤当必然发生。返回可达死锁或循环反例；通过则给严格递减rank和最多转换步数。它不验证状态含义、异议是否真正新、模型完整性、目标是否有价值、现实时间或首次到目标后的行为，也不默认公平调度。将时间步、输入假设及遗漏行为写入assumptions；单点布尔公式不能替代时序图。1次CPU工具，0内部模型调用。',
  {'states':{'type':'object','minProperties':1,'maxProperties':32,'additionalProperties':{'type':'string','minLength':1,'maxLength':500}},
   'initial':{'type':'string','minLength':1,'maxLength':80},
   'goals':{'type':'array','minItems':1,'maxItems':32,'uniqueItems':True,'items':{'type':'string','minLength':1,'maxLength':80}},
   'transitions':{'type':'array','maxItems':128,'items':{'type':'object','properties':{'source':{'type':'string','minLength':1,'maxLength':80},'target':{'type':'string','minLength':1,'maxLength':80},'label':{'type':'string','minLength':1,'maxLength':160}},'required':['source','target','label'],'additionalProperties':False}},
   'assumptions':{'type':'array','items':TEXT,'minItems':1,'maxItems':12},'prediction':TEXT}),
 function('check_entailment','检查明确布尔形式化的前提能否推出结论，枚举最多8个变量的全部真假赋值。variables将ASCII变量名映射为含义；premises/conclusion用变量、True/False或0/1、not/and/or、==/!=，每式最多160字符，最多12条前提。返回前提相容赋值数、支持/反模型数和各最多3个例子；区分entailed/refuted/underdetermined/inconsistent_premises。反模型仅证明给定公式不足，不能断言真实人物如此；前提矛盾不能当任意结论的有效依据。变量含义、原话到公式的翻译、桥梁假设和现实可能性都未被验证，必须写入assumptions；不要先把待证明的推断写成前提再声称得到证明。无需线性效应模型，不用它冒充现实观测。1次CPU工具，不消耗内部模型请求。',
  {'variables':{'type':'object','maxProperties':8,'additionalProperties':{'type':'string','minLength':1,'maxLength':500}},
   'premises':{'type':'array','maxItems':12,'items':{'type':'string','minLength':1,'maxLength':160}},
   'conclusion':{'type':'string','minLength':1,'maxLength':160},
   'assumptions':{'type':'array','items':TEXT,'minItems':1,'maxItems':12},'prediction':TEXT}),
 function('check_design','检查明确给定线性模型的设计能否区分目标效应。每行是一个计划观察，列为terms中的系数项（含基线需显式填1），预测=X*beta；contrast选择要识别的系数组合，例如[0,1]选择第二个系数。返回精确有理数证书：若不可识别，改变系数而所有预测不变；若可识别，给观察的线性组合。列须包含待排除的替代机制，遗漏列会使可识别结论依赖遗漏假设。须把编码、遗漏效应、独立性等写明为假设；无现实数据，不证明因果或提问有效。每次仅查一个设计，1次工具额度，不消耗内部模型请求。',
  {'terms':{'type':'array','items':{'type':'string','maxLength':80},'minItems':1,'maxItems':8,'uniqueItems':True},
   'rows':{'type':'array','items':{'type':'array','items':{'type':'number','minimum':-10000,'maximum':10000},'minItems':1,'maxItems':8},'minItems':1,'maxItems':32},
   'contrast':{'type':'array','items':{'type':'number','minimum':-10000,'maximum':10000},'minItems':1,'maxItems':8},
   'assumptions':{'type':'array','items':TEXT,'minItems':1,'maxItems':12},'prediction':TEXT}),
 function('diagnose_experiment','复核已展示的成功experiment回执。冻结原参数、派生公式与未选条件；只对顶层and指定序号的单个==比较加绝对容差，返回原始与容差结果，不改原回执。浮点诊断优先用此工具；不能选OR、非等式或链式比较。序号从0开始，prediction说明单位/尺度，不是精确证明。',
  {'source_event':{'type':'integer'},'equality_indices':{'type':'array','items':{'type':'integer','minimum':0},'minItems':1,'maxItems':8,'uniqueItems':True},'absolute_tolerance':{'type':'number','exclusiveMinimum':0},'prediction':TEXT}),
 function('calculate','实际执行单个Python风格纯算式，只支持+-*/和**乘方（不是^），不接受函数/循环/print/sum/comb。先说明来源/单位/假设和预期；只算表达式，不验证basis推导，不是现实实测。净收益0是持平，不是正收益。',
  {'expression':{'type':'string','maxLength':300},'basis':TEXT,'prediction':TEXT}),
 function('search','实际搜索相关依据或反例，说明要区分什么解释。搜索返回外部主张，不证明真伪。',
  {'query':{'type':'string','maxLength':128},'prediction':TEXT}),
 function('read_source','读取本场搜索实际返回的HTTPS原文；不支持PDF，失败和截断必须如实报告。',
  {'url':TEXT,'prediction':TEXT}),
 function('experiment','实际枚举有限参数网格，分别返回最多10个passing_examples（满足整个断言）和counterexamples，以及前10个sample_points（可能全不满足）。找可行方案时用passing_examples，计数不是具体方案；空通过集不能编造方案。component_checks按顶层and子项顺序给失败计数，failed_numeric_comparisons给最多2个失败点的左右值与差值，不能从区间端点猜点值或把合取失败归给每个子命题。assertion和派生量都逐个参数点评估，互斥参数点不能在同一点合取。binary_derived_counts给全网格中始终为0/1的派生量的zero/one总数，不受样本截断影响；该统计不是可在公式中引用的变量，逐点标记不能拿来与全网格总数比较。数值派生式可把比较结果按当前点的0/1参与运算，如(a==1)+(b==1)或a*(H>=W)，0/1标记可直接作断言或and/or的条件，其他计数须显式比较（如count>0）；最多8个派生量。但输入参数仍须有限数值、不能是布尔。公式是单个Python纯表达式，乘方用**不是^，不接受函数/循环（含abs），变量须声明；容差可写(a-b)**2 <= eps**2，勿为过关放松其他条件。不是现实实验或域外证明。',
  {'parameters':{'type':'object','maxProperties':5,'additionalProperties':{'type':'array','items':{'type':'number'},'minItems':1,'maxItems':20}},
   'derived':{'type':'object','maxProperties':8,'additionalProperties':{'type':'string','maxLength':300}},
   'assertion':{'type':'string','maxLength':300},'assumptions':{'type':'array','items':TEXT,'minItems':1,'maxItems':12},'prediction':TEXT}),
 function('text_experiment','实际比较普通摘要与判断轨迹记录，经只看记录的读取者重建，再核对指定原句和引文。用已展示原始用户/工具事件；消耗最多4次同场模型请求，须另留1次综合。只观察字面保留，不评分真理或完整性。',
  {'source_events':{'type':'array','items':{'type':'integer'},'minItems':1,'maxItems':4},
   'probes':{'type':'array','minItems':1,'maxItems':4,'items':{'type':'object','properties':{'question':TEXT,'event':{'type':'integer'},'quote':TEXT},'required':['question','event','quote'],'additionalProperties':False}},'prediction':TEXT}),
 function('map_inquiry','保存当前故事的问题组织，不是新验证。links只选当前上下文citation_anchors的整数anchor，anchor_run照抄当前运行标识，不复抄source_event/quote；模型片段只能context，工具片段只是有限观测。根问题仍用本故事用户origin_event/origin_quote；子问题可多父。parents/question中整数为已展示问题event，字符串为本批key；新问题revises=null，框架改变可用旧问题event，不自动迁移旧子问题。supports/challenges须指定已展示knowledge_proposal；未有候选时proposition=null且只能context。组织不认证真理。',
  {'questions':{'type':'array','maxItems':6,'items':{'type':'object','properties':{'key':TEXT,'text':TEXT,'parents':{'type':'array','items':{'type':['integer','string']},'maxItems':4},'origin_event':{'type':'integer'},'origin_quote':TEXT,'revises':{'type':['integer','null']}},'required':['key','text','parents','origin_event','origin_quote','revises'],'additionalProperties':False}},
   'links':{'type':'array','maxItems':12,'items':{'type':'object','properties':{'question':{'type':['integer','string']},'proposition':{'type':['integer','null']},'anchor':{'type':'integer','minimum':1},'relation':{'type':'string','enum':['supports','challenges','context']},'explanation':TEXT},'required':['question','proposition','anchor','relation','explanation'],'additionalProperties':False}},'anchor_run':{'type':'string','pattern':'^[0-9a-f]{32}$'},'prediction':TEXT})
]
