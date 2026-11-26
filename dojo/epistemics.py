"""Source-bounded critique proposals. They are checks to inspect, not truth ratings."""
import json
import re
from .live import LiveError,_no_duplicate_keys

PROMPT='''你检查一段答复的结论力度，不给满意度或真理分数。只用给定公开对话和工具材料。不是挑刺比赛：条件明确、已经标为猜测或有有效推导的内容不应因“没有现实实测”就被否定。也不能因为用户喜欢、或有几份检索摘录就升级事实。
来源分层：user只能支持“用户报告了什么”，tool_result只能支持实际执行状态及其有限结果；model_interpretation、草稿和以往模型回答都是待查解释，不能证明用户经历、第三方动作或世界事实。一个细节即使在过去回答里出现，也必须回到用户/工具原始来源检查；只在模型话语中出现的具体动作不能被再次引用就洗成事实。来源未提及不等于现实不存在；“尚未看到”在明确的当前材料语境中不必挑成全世界断言。
story_scope=other_story或unknown的用户报告不能自动归成当前用户经历，不能据此说“你之前讲过”；可以明确作为另一段历史材料类比。same_story的原话可用于显式续谈。来源标签不认证内容真值。
先核对答复是否把计划/失败/后台提议说成已经执行的工具。execution_ledger是运行器按当前故事和身份截至草稿时点的完整回执计数，不是模型意见；sources只是一部分材料，不能用其缺席代替完整账本。story_counts与current_run_counts分开；executed=0时不能声称此范围已执行，failed/not_executed不算成功，其他工具也不能冒充该调用，后台关联不等于map_inquiry。计数证明执行发生，不证明结果正确、做过现实验证或读过全文；结果内容仍回看原回执，未展示内容保持未知。未执行事实的具体断言优先于一般措辞问题；建议仍可提该工具，明确计划/未执行不能被误判为完成声明。
检查第三方心理/动机是否被当成已知、假想细节是否伪装成经历、个案/局部研究是否被推广为普遍机制、以及“不能兼得/只能”是否真有不可兼得的前提。必要时提出一个具体反例或替代机制。不要把未发生的实验当作已经跑过，不把最终选择或验证责任统统交回用户；保留用户原目标和有价值的构想。
用户同意/否掉候选、跨场合一致，不单独证明知识真值或脑内来源；候选尚无独立依据时不能预标真假再凭反应验证。检查修正方案是否只换了同样不充分的代理判据。新形成的想法仍可有价值，来源不可识别不必阻塞对候选理由本身及适用条件的独立验证；不能以保留未知为由撤掉主动贡献和可负担验证。
对实验或测试方案，按干预、任务运行、观察的时序核对它能排除哪些替代解释。某阶段的运行成功不能替代另一阶段的运行证据；等待时间不自动证明任务成功完成。建议修正必须补齐真正缺的观察，不仅把“唯一方案”改成“方案之一”。有充分条件的结论保留，不为挑错强造反例。
只输出JSON对象，键只能是issues。issues为空数组或最多6个对象，每项为span、kind、reason、counterexample、rewrite。span选择draft_spans中正整数span，程序恢复逐字原文；不复抄、不省略Markdown、不输出旧quote格式。kind为unsupported_fact/invented_detail/false_dilemma/scope_leap。reason说明哪条实际来源支持不到什么程度；counterexample为标明是假设的反例/替代机制，或现有材料里可指认的矛盾；rewrite保留能成立的部分，改成恰当条件或明确假设，不只加空泛免责声明。
完整无问题示例：{"issues":[]}。你自己的判断也可能错，不能授予“已验证”状态。'''

def packet(draft,sources):
 spans=[];start=0
 for end in [m.end() for m in re.finditer(r'[。！？\n]',draft)]+[len(draft)]:
  while start<end:
   stop=min(end,start+600);text=draft[start:stop];left=len(text)-len(text.lstrip());right=len(text.rstrip())
   if right>left:spans.append({'span':len(spans)+1,'start':start+left,'end':start+right,'quote':text[left:right]})
   start=stop
   if len(spans)>=64:break
  if len(spans)>=64:break
 return {'draft':draft,'sources':sources,'draft_spans':spans,'draft_spans_truncated':start<len(draft),'citation_contract':'exact_draft_spans_v1'}


def validate(content):
 try:
  v=json.loads(content,object_pairs_hook=_no_duplicate_keys)
  if not isinstance(v,dict) or set(v)!={'issues'} or not isinstance(v['issues'],list) or len(v['issues'])>6:raise ValueError()
  for issue in v['issues']:
   if not isinstance(issue,dict):raise ValueError()
   anchored='span' in issue
   if set(issue)!=({'span','kind','reason','counterexample','rewrite'} if anchored else {'quote','kind','reason','counterexample','rewrite'}):raise ValueError()
   if anchored and (type(issue['span']) is not int or issue['span']<=0):raise ValueError()
   if issue['kind'] not in {'unsupported_fact','invented_detail','false_dilemma','scope_leap'}:raise ValueError()
   for key in (('reason','counterexample','rewrite') if anchored else ('quote','reason','counterexample','rewrite')):
    if not isinstance(issue[key],str) or not issue[key].strip() or len(issue[key])>4000:raise ValueError()
  return v
 except (ValueError,TypeError,RecursionError):raise LiveError('结论审查格式不合约',kind='critique_schema') from None


def grounded(packet,critique):
 validate(json.dumps(critique,ensure_ascii=False))
 spans={s['span']:s for s in packet.get('draft_spans',[])};issues=[];resolutions=[]
 for index,issue in enumerate(critique['issues']):
  if 'span' in issue:
   span=spans.get(issue['span'])
   if span is None or type(span['start']) is not int or type(span['end']) is not int or not 0<=span['start']<span['end']<=len(packet['draft']) or packet['draft'][span['start']:span['end']]!=span['quote']:
    raise LiveError('审查未选择实际答复片段',kind='critique_quote_mismatch')
   issues.append({k:v for k,v in issue.items() if k!='span'}|{'quote':span['quote']})
   resolutions.append({'issue':index,'span':span['span'],'start':span['start'],'end':span['end']})
  else:
   if issue['quote'] not in packet['draft']:raise LiveError('审查未引用实际答复片段',kind='critique_quote_mismatch')
   issues.append(issue)
 return {'issues':issues,**({'span_resolutions':resolutions} if resolutions else {}),'epistemic_status':'model_critique_not_truth_verdict'}
