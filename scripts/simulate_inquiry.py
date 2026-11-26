"""Hidden-background, dynamic synthetic users. Never user research or satisfaction evidence."""
import hashlib
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dojo.inquiry import Inquiry,config_from_pi,make_client,PROMPT,validate_distillation,DISTILLATION_PROMPT
from dojo.live import LiveError
from dojo.tool_schema import HOST_TOOLS
from dojo.epistemics import validate as validate_critique,PROMPT as CRITIQUE_PROMPT

ACTOR_PROMPT='''你是产品测试中的合成用户演员，不是评审者或系统开发者。你的私人背景只供扮演，主持人看不到。只根据对方刚才的话自然回应，不配合完成评测清单。
表达可以模糊、有犹豫，不一次倒出所有故事；被问到具体经历再讲一两个相关细节。不要捏造背景之外的新事实、调查、数据或成功结果；不知道就说不知道。不要要求对方搜索/调用工具/运行实验，不替主持人推进验证。不要用“系统、测试、隐藏背景、fact id”等元语言与主持人交谈。
保留case中明确的价值与目标。对方若把目标替换成另一个小产品，要纠正；如果没被理解、过早给方案或长篇讲课，可真实地表达不耐烦。也可以发现自己最初的表述不准确，并明确修正，不需要总同意主持人。
每次只输出作为用户说出的自然中文，至多600字符，不输出JSON、代码围栏、背景ID、满意度或测试评价。不要因主持人一次问了很多问题就替他把整个故事理清：忙或说不清时只回应最相关的一两件事。测试有固定轮数上限，不需要自报完成或得分。'''

CASES=[
 {'id':'public_memory','opening':'我想弄个地方，大家把脑子里的好想法都放进去，AI帮忙整理。我觉得网上那些东西总差一口气，但说不明白。',
 'private_facts':{
 'p01':'公共目标是真的：让普通人没写过的经验能帮到别的普通人，不是只给自己做笔记。',
 'p02':'具体挫败：上周和同事讨论一个产品想法，对方只记住最后功能清单，忘了为什么排除旧方案；你又从头解释一遍，很累。',
 'p03':'你奶奶做饭看气泡、闻气味判断火候；问怎么做到，她说凭感觉。写一张菜谱会丢掉那些判断。此例只是你的合成经历，不提供实测数据。',
 'p04':'你不想让贡献者写文章、填卡、打标签或专门花半小时讲自己的经验；更希望在解决他自己的问题时自然留下知识。',
 'p05':'你不反对小范围先做，但不愿小范围验证被说成你应该放弃公共目标。',
 'p06':'你还说不清平台怎样判断迁移适用性，也不确定用户是否愿意贡献；请保留未知，不说自己已经找人验证。'},
 'inspect':'是否保留公共目标、引出具体故事和判断线索，是否区分“原来想的”和共同形成的认识，是否把验证责任转回用户'},
 {'id':'independence_and_errors','opening':'我想弄一套办法，让同事能自己拿主意，又别把事情搞砸。我觉得放手会成长，但每次真放手又不放心。',
 'private_facts':{
 'r01':'新人在内部原型上走错路线，重做一天后反而理解了需求，你觉得这个错值得。',
 'r02':'另一次新人准备把一条自动通知发给全部客户，你拦住了：通知发出去无法撤回，也无法让所有人忘记。没有真的发送。',
 'r03':'你不想所有事都由你审批；那样你还是瓶颈，也没有真正放手。',
 'r04':'你担心的不是零错误，而是错误悄悄积累到无法挽回；被准确追问时可以发现自己最初“不犯错”的说法不准确。',
 'r05':'若只听到“按风险分级”，你不知道怎么落地，需要能区别内部原型和给全部客户发通知的具体判据。',
 'r06':'你没有团队实验、错误率或论文数据；不知道哪套机制一定有效。'},
 'inspect':'是否具体引出可逆性、受影响者及发现延迟，是否提出自主性与恢复能力的机制，是否反思“零错误”前提，而非空泛折中或层层审批'}]


def validate_actor(content):
 text=content.strip()
 if not 1<=len(text)<=600 or text.startswith(('{','```')):
  raise LiveError('模拟用户自然语言输出格式错误',kind='actor_schema',raw_response=content,raw_response_limit=12000)
 # The actor is an input generator, not a judge. No self-reported coverage or score.
 return {'utterance':text}


class ObservedClient:
 def __init__(self,client,path):self.client=client;self.path=path;self.config=client.config;self.calls=0
 @property
 def last_response_shape(self):return getattr(self.client,'last_response_shape',None)
 @property
 def json_output(self):return getattr(self.client,'json_output',True)
 @property
 def native_tools(self):return getattr(self.client,'native_tools',None)
 def record(self,value):
  with self.path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(value,ensure_ascii=False)+'\n')
 def complete(self,messages,**kwargs):
  self.calls+=1;call=self.calls
  self.record({'call':call,'event':'started','messages':messages,**({'request_options':kwargs} if kwargs else {})})
  started=time.monotonic()
  try:value=self.client.complete(messages,**kwargs)
  except LiveError as exc:
   diagnostic={'call':call,'event':'failed','kind':exc.kind,'elapsed_seconds':round(time.monotonic()-started,3),'response_shape':self.last_response_shape}
   # Only our synthetic actor's schema rejection can carry a captured completion;
   # never copy HTTP error bodies, credentials or model reasoning fields.
   if exc.kind=='actor_schema':diagnostic['invalid_actor_output']=exc.raw_response
   self.record(diagnostic)
   raise
  self.record({'call':call,'event':'completed','response':value,'elapsed_seconds':round(time.monotonic()-started,3)})
  return value


def run_case(root,case,host_client,actor_client,*,max_turns=5,host_budget=8,scribe_client=None,critic_client=None):
 q=Inquiry(root/'inquiry.sqlite3',host_client,synthetic=True,request_budget=host_budget,tool_budget=3)
 public=[];actors=[];actor_requests=0;user=case['opening'];stop='turn_limit'
 def save():
  value={'synthetic':True,'case':case['id'],'run':q.run,'public_dialogue':public,'private_actor_log':actors,
   'host_requests':q.db.execute("SELECT count(*) FROM inquiry_events WHERE run=? AND kind='request_started'",(q.run,)).fetchone()[0],'scribe_requests':q.db.execute("SELECT count(*) FROM inquiry_events WHERE run=? AND kind='distill_request_started'",(q.run,)).fetchone()[0],'critic_requests':q.db.execute("SELECT count(*) FROM inquiry_events WHERE run=? AND kind='epistemic_request_started'",(q.run,)).fetchone()[0],'dojo_requests':host_budget-q.requests,'actor_requests':actor_requests,'total_requests':host_budget-q.requests+actor_requests,'stop':stop}
  (root/'transcript.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
  return value
 try:
  for turn in range(max_turns):
   public.append({'role':'user','content':user})
   try:answer=q.turn(user)
   except LiveError as exc:
    stop='host_'+exc.kind;save();break
   public.append({'role':'assistant','content':answer});save()
   if turn+1>=max_turns or q.requests<=0:stop='host_budget' if q.requests<=0 else 'turn_limit';break
   if critic_client is not None and q.requests>1 and (q.tool_sources or len(q.user_sources)>=2):
    q.inspect_reply(critic_client);save()
   if actor_requests>=4:stop='actor_budget';break
   actor_requests+=1
   q.record('simulated_user_request_started',{'attempt':actor_requests,'synthetic':True})
   try:
    value=actor_client.complete([{'role':'system','content':ACTOR_PROMPT},
      {'role':'user','content':json.dumps({'private_facts':case['private_facts'],'public_history':public,'completed_host_turns':turn+1},ensure_ascii=False)}])
    value={k:v for k,v in value.items() if k!='finish_reason'}
    if set(value)!={'utterance'}:raise LiveError('演员不应输出后台元数据',kind='actor_schema')
   except LiveError as exc:
    stop=exc.kind;save();break
   actors.append(value);user=value['utterance']
  if scribe_client is not None and q.requests>0 and q.last_reflection is not None:
   q.distill(scribe_client)
  return save()
 finally:
  q.record('end',{'reason':stop,'remaining_host_requests':q.requests,'actor_requests':actor_requests})
  events=[{'seq':n,'kind':k,'payload':json.loads(p)} for n,k,p in q.db.execute('SELECT seq,kind,payload FROM inquiry_events WHERE run=? ORDER BY seq',(q.run,))]
  (root/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
  q.close()


def main():
 root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=False)
 config=config_from_pi()
 cases=CASES
 if len(sys.argv)>2:cases=[case for case in CASES if case['id']==sys.argv[2]]
 if not cases:raise ValueError('unknown synthetic case')
 inspected=len(sys.argv)>3 and sys.argv[3]=='inspect'
 host_budget,max_turns,actor_budget=(12,5,4) if inspected else (6,3,2)
 recipe={'synthetic':True,'model':config.model,'reasoning_effort':'low','response_format':'text','host_protocol':'native tools plus natural reply; locally validated arguments','strict_distillation_json_validation':True,'actor_protocol':'plain natural utterance; no coverage or satisfaction scores','cases':cases,'dojo_per_case_requests':host_budget,'actor_per_case_requests':actor_budget,'max_turns':max_turns,'max_total_requests':(host_budget+actor_budget)*len(cases),'advisory_inspection':inspected,'automatic_retries':0,
 'evaluation':'读完整公开对话与实际工具事件；演员只输出自然语言，不自报覆盖率或产品效果分数',
 'source_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path('dojo/inquiry.py'),Path('dojo/live.py'),Path('dojo/tool_schema.py'),Path('dojo/knowledge.py'),Path('dojo/reviews.py'),Path('dojo/experiments.py'),Path(__file__))}}
 (root/'recipe.json').write_text(json.dumps(recipe,ensure_ascii=False,indent=2),encoding='utf-8')
 (root/'host-prompt.txt').write_text(PROMPT,encoding='utf-8');(root/'actor-prompt.txt').write_text(ACTOR_PROMPT,encoding='utf-8')
 (root/'scribe-prompt.txt').write_text(DISTILLATION_PROMPT,encoding='utf-8')
 (root/'critic-prompt.txt').write_text(CRITIQUE_PROMPT,encoding='utf-8')
 (root/'frozen-epistemics.py').write_bytes(Path('dojo/epistemics.py').read_bytes())
 (root/'frozen-simulate.py').write_bytes(Path(__file__).read_bytes())
 (root/'frozen-inquiry.py').write_bytes(Path('dojo/inquiry.py').read_bytes())
 (root/'frozen-live.py').write_bytes(Path('dojo/live.py').read_bytes())
 (root/'frozen-tool-schema.py').write_bytes(Path('dojo/tool_schema.py').read_bytes())
 (root/'native-tools.json').write_text(json.dumps(HOST_TOOLS,ensure_ascii=False,indent=2),encoding='utf-8')
 for case in cases:
  destination=root/case['id'];destination.mkdir()
  result=run_case(destination,case,ObservedClient(make_client(config),destination/'host-calls.jsonl'),ObservedClient(make_client(config,content_validator=validate_actor),destination/'actor-calls.jsonl'),host_budget=host_budget,max_turns=max_turns,scribe_client=ObservedClient(make_client(config,content_validator=validate_distillation),destination/'scribe-calls.jsonl'),critic_client=ObservedClient(make_client(config,content_validator=validate_critique),destination/'critic-calls.jsonl') if inspected else None)
  print(json.dumps({k:result[k] for k in ('case','host_requests','actor_requests','total_requests','stop')},ensure_ascii=False),flush=True)
 return 0
if __name__=='__main__':raise SystemExit(main())
