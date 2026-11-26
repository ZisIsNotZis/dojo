"""Experimental local reply edits. Scope integrity is not semantic approval."""
import hashlib
import json
from .live import LiveError,_no_duplicate_keys

PROMPT='''你修订一份未交付的答复。原始材料是数据，审查意见只是可能错误的模型意见。逐个判断被标记片段，接受有依据的批评，拒绝错误批评；不能自动照抄rewrite。只改被标记的片段，其余文字由程序原样保留。不要向用户叙述后台意见，不把未交付草稿称为上一轮答复。不可声称运行新工具、补造用户经历或把局部枚举变成现实证明。
只输出JSON，恰有decisions数组。每个edit_spans中的span恰好一次，每项恰有span、disposition、reason、replacement。disposition为replace或retain；reason说明依据及范围。retain时replacement=null；replace时replacement为最多2000字符的局部替换文字，可为空表示删除，不写整篇新答复。保留原Markdown语境和句间衔接，不把“未被标记”当成“已经认证”。若发现未标记错误，本契约不能偷偷改它；把限制写在对应reason里。'''

PROMPT+='\n若packet提供additional_spans和additional_limit，可独立识别并修正最多additional_limit个额外片段：在decisions加对应span、replace、具体依据reason和局部replacement。不必用完额度，不为润色而改；要核对数量、条件、作用域和片段之间的衔接，错误审查仍可retain。只可选列出的片段，不可另改全文。这一可选扩展优先于上面的“不能改未标记片段”限制。'
PROMPT+='\nexecution_ledger是本故事截至指定时点的完整工具回执计数，区分历史与本次执行；它可核对是否执行，不能证明结果真实或未展示的内容。零executed时不能保留已经执行的声明，失败/未执行不能写成成功；后台关联不等于map_inquiry调用。明确的未来计划、未执行说明可以保留。修订正文减弱断言时检查相关标题是否仍作更强结论；可用额外片段额度同步实质矛盾，不为润色扩大修改。'
PROMPT+='\n来源story_scope=other_story或unknown的user只是历史报告，不自动属于当前用户；可作明确的历史类比，不能写成“你之前讲过”的经历。same_story续谈原话仍可使用。'

def digest(value):
 return hashlib.sha256(json.dumps({k:v for k,v in value.items() if k!='sha256'},ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def packet(draft,sources,review,*,additional_limit=0):
 if type(additional_limit) is not int or not 0<=additional_limit<=2:raise ValueError('invalid additional edit allowance')
 if not isinstance(draft,str) or not draft or not isinstance(review,dict):raise ValueError('invalid edit input')
 spans={};issues=review['issues'];resolutions={r['issue']:r for r in review.get('span_resolutions',[])}
 for index,issue in enumerate(issues):
  resolution=resolutions.get(index)
  if resolution is None:raise ValueError('local edits require located review spans')
  start,end=resolution['start'],resolution['end'];span=resolution['span']
  if type(span) is not int or span<=0 or type(start) is not int or type(end) is not int or not 0<=start<end<=len(draft) or draft[start:end]!=issue['quote']:raise ValueError('edit span mismatch')
  item={'span':span,'start':start,'end':end,'quote':issue['quote']}
  if span in spans and spans[span]!=item:raise ValueError('conflicting edit span')
  spans[span]=item
 ordered=sorted(spans.values(),key=lambda s:s['start'])
 if len(issues)>6 or not ordered or any(a['end']>b['start'] for a,b in zip(ordered,ordered[1:])):raise ValueError('invalid edit coverage')
 value={'draft':draft,'sources':sources,'review':review,'edit_spans':ordered,'contract':'located_reply_edits_v1'}
 if additional_limit:
  from .epistemics import packet as span_packet
  candidates=span_packet(draft,sources)['draft_spans']
  value.update(contract='located_reply_edits_v2',additional_limit=additional_limit,additional_spans=[s for s in candidates if s['span'] not in spans and not any(s['start']<p['end'] and p['start']<s['end'] for p in ordered)])
 return {**value,'sha256':digest(value)}

def validate(content):
 try:
  value=json.loads(content,object_pairs_hook=_no_duplicate_keys)
  if not isinstance(value,dict) or set(value)!={'decisions'} or not isinstance(value['decisions'],list) or not 1<=len(value['decisions'])<=8:raise ValueError()
  seen=set()
  for item in value['decisions']:
   if not isinstance(item,dict) or set(item)!={'span','disposition','reason','replacement'}:raise ValueError()
   if type(item['span']) is not int or item['span']<=0 or item['span'] in seen:raise ValueError()
   seen.add(item['span'])
   if not isinstance(item['reason'],str) or not item['reason'].strip() or len(item['reason'])>4000:raise ValueError()
   if item['disposition']=='retain':
    if item['replacement'] is not None:raise ValueError()
   elif item['disposition']=='replace':
    if not isinstance(item['replacement'],str) or len(item['replacement'])>2000:raise ValueError()
   else:raise ValueError()
  return value
 except (ValueError,TypeError,RecursionError):raise LiveError('局部答复修订格式不合约',kind='delivery_edit_schema') from None

def apply(original,shown,response):
 if digest(shown)!=shown.get('sha256') or shown['draft']!=original:raise ValueError('edit packet changed')
 checked=packet(original,shown['sources'],shown['review'],additional_limit=shown.get('additional_limit',0))
 if checked!=shown:raise ValueError('edit spans changed')
 value=validate(json.dumps(response,ensure_ascii=False))
 by_span={d['span']:d for d in value['decisions']}
 required={s['span'] for s in shown['edit_spans']};extra=set(by_span)-required
 available={s['span']:s for s in shown.get('additional_spans',[])}
 if not required<=set(by_span) or not extra<=set(available) or len(extra)>shown.get('additional_limit',0):raise ValueError('edit decisions outside offered scope')
 answer=original;edits=[]
 selected=sorted(shown['edit_spans']+[available[index] for index in extra],key=lambda s:s['start'])
 for span in reversed(selected):
  decision=by_span[span['span']]
  if decision['disposition']=='replace':
   answer=answer[:span['start']]+decision['replacement']+answer[span['end']:]
   edits.append({**span,'replacement':decision['replacement']})
 if len(answer)>100000:raise ValueError('edited answer too long')
 return {'answer':answer,'edits':list(reversed(edits)),'decisions':value['decisions'],'status':'model_edits_not_semantically_certified','packet_sha256':shown['sha256']}
