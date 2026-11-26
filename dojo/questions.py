"""Question organization and proposed evidence relations over the event ledger.

Organization edges are not inference premises; relation labels are model opinions.
"""
import json
from pathlib import Path
import re
import sqlite3
from datetime import datetime,timezone
from .knowledge import Knowledge
from .stories import run_index

KINDS=('inquiry_question','question_parent','question_evidence')

class QuestionMapError(ValueError):
    def __init__(self,reason):
        super().__init__(reason)
        self.kind='question_map_validation'
        self.validation_code=re.sub('[^a-z0-9_]+','_',reason.lower())[:80]
        self.repair_hint=(
            '原生links使用当前anchor_run与citation_anchors编号，不从旧运行复制编号；目录片段不代表命题已验证，模型片段仅context。'
            '旧result中的basis/assumptions/assertion/domain及模型生成文本仍是输入或解释，不是观测；calculate引用value，experiment引用计算样本或计数，text_experiment仅引字面计数；保存问题图不能作为事实证据。'
            'reflection/epistemic_check是模型解释或意见，只能连context，不能作为supports/challenges。'
            '对工具，supports/challenges只能引用真实result或失败状态，action/prediction只能context。'
            'supports/challenges必须指定已展示knowledge_proposal event作为proposition，并引用另一实际来源；没有实证可全部保留context。'
            'origin_quote/quote必须逐字存在于已展示source.text。根问题origin必须来自当前故事用户原话。'
            'parents/question的字符串是本批key，整数是已展示的问题event；新题revises=null。已替换问题不能作为新父问题。')

def link_provenance_error(knowledge,dependencies,source,quote,claim):
    """Why provenance forbids evidence use; None is not semantic validation."""
    if source['kind'] in {'reflection','epistemic_check'}:return 'model opinion only provides context'
    if source['kind']=='tool_result' and quote not in knowledge.observed_tool_text(source['event']):return 'tool plan is not an observation'
    if source['event']==claim or dependencies.depends_on(source['event'],claim,include_execution_context=False):return 'candidate cannot support or challenge itself through an echo'
    return None


def cited_source_state(knowledge,event):
    """One sentence about the quotation a relation rests on, read from the ledger now.

    The relation's own `dependency_status` says whether the *relation* moved; it
    says nothing about the source it quotes. Measured on the repo's real files:
    25 live relations quote an event that a later revision replaced, and nothing
    on the screen said so. Four outcomes, kept as four sentences on purpose -- a
    boolean would collapse 'still standing' with 'could not be read', which is
    the mistake this chain has already paid for twice.
    """
    try:
        status=knowledge.dependencies.status(event)
    except (ValueError,IndexError):
        # A cited event id with no row must not fall through to a silence that
        # reads like 'fine', and must not be called stale either.
        return '这条关系所引的原事件（%s）在本库里找不到：读不出来时不说它有效，也不说它失效。' % event
    state=status['state']
    if state=='superseded':
        replacement=status.get('replacement')
        return ('这条关系所引的那句原话后来已被换掉（原事件 %s，换成了事件 %s）：'
                '保留原句是因为这里记录的是它当时的样子，不是因为它现在还成立。' % (event,replacement))
    if state=='current_interpretation':
        return '这条关系所引的那句原话仍然在架（事件 %s），但这只说明它没被替换，不说明它支持得住。' % event
    if state=='needs_review':
        return ('这条关系所引的那句原话本身还在等复核（事件 %s）：它既没被替换，也还没站住，'
                '所以引用它不构成已核实的依据。' % event)
    return '这条关系所引的那句原话状态未分类（事件 %s，库内状态 %r）：读不出来时不说它有效，也不说它失效。' % (event,state)


def validate_action(action):
    if not isinstance(action,dict) or set(action)!={'kind','questions','links','prediction'} or action['kind']!='map_inquiry':raise QuestionMapError('invalid question map fields')
    if not isinstance(action['questions'],list) or len(action['questions'])>6 or not isinstance(action['links'],list) or len(action['links'])>12:raise QuestionMapError('question map too large')
    if not action['questions'] and not action['links']:raise QuestionMapError('empty question map')
    keys=set();texts=set()
    def text(value,maximum):return isinstance(value,str) and bool(value.strip()) and len(value)<=maximum
    def ref(value):return type(value) is int or isinstance(value,str) and bool(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}',value))
    for q in action['questions']:
        if not isinstance(q,dict) or set(q)!={'key','text','parents','origin_event','origin_quote','revises'}:raise QuestionMapError('invalid question fields')
        if not isinstance(q['key'],str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}',q['key']) or q['key'] in keys:raise QuestionMapError('invalid local question key')
        if not text(q['text'],2000) or not text(q['origin_quote'],2000) or type(q['origin_event']) is not int:raise QuestionMapError('invalid question origin')
        if not isinstance(q['parents'],list) or len(q['parents'])>4 or any(not ref(p) for p in q['parents']):raise QuestionMapError('invalid question parents')
        if q['revises'] is not None and type(q['revises']) is not int:raise QuestionMapError('invalid question revision')
        canonical=' '.join(q['text'].split())
        if canonical in texts:raise QuestionMapError('duplicate local question text')
        texts.add(canonical);keys.add(q['key'])
    for link in action['links']:
        if not isinstance(link,dict) or set(link)!={'question','proposition','source_event','quote','relation','explanation'}:raise QuestionMapError('invalid question link')
        if not ref(link['question']) or type(link['source_event']) is not int or link['proposition'] is not None and type(link['proposition']) is not int:raise QuestionMapError('invalid link reference')
        if link['relation'] not in {'supports','challenges','context'} or not text(link['quote'],2000) or not text(link['explanation'],3000):raise QuestionMapError('invalid link text')
        if link['relation']!='context' and link['proposition'] is None:raise QuestionMapError('support/challenge needs a candidate proposition')
    if not text(action['prediction'],2000):raise QuestionMapError('invalid map prediction')

def validate_native_action(action):
    if not isinstance(action,dict) or 'anchor_run' not in action:
        validate_action(action);return
    if set(action)!={'kind','questions','links','prediction','anchor_run'} or not isinstance(action['anchor_run'],str) or not re.fullmatch(r'[0-9a-f]{32}',action['anchor_run']):raise QuestionMapError('invalid native anchor run')
    if not isinstance(action['links'],list):raise QuestionMapError('invalid native links')
    links=[]
    for link in action['links']:
        if not isinstance(link,dict) or set(link)!={'question','proposition','anchor','relation','explanation'} or type(link['anchor']) is not int or link['anchor']<=0:raise QuestionMapError('invalid native link anchor')
        links.append({k:v for k,v in link.items() if k!='anchor'}|{'source_event':1,'quote':'anchor'})
    validate_action({k:v for k,v in action.items() if k not in {'anchor_run','links'}}|{'links':links})

def resolve_native_action(q,action):
    validate_native_action(action)
    if 'anchor_run' not in action:return action
    if action['anchor_run']!=q.run:raise QuestionMapError('native anchors belong to another run')
    links=[]
    for link in action['links']:
        try:anchor=q.front_anchors.resolve(q.knowledge,link['anchor'],q.visible_source_text,relation=link['relation'],synthetic=q.synthetic)
        except ValueError as error:raise QuestionMapError(str(error)) from None
        links.append({k:v for k,v in link.items() if k!='anchor'}|{'source_event':anchor['source_event'],'quote':anchor['quote']})
    return {k:v for k,v in action.items() if k not in {'anchor_run','links'}}|{'links':links}


class Questions:
    def __init__(self,db,knowledge):self.db=db;self.knowledge=knowledge

    def events(self,story=None):
        values=[]
        for event,run,kind,payload in self.db.execute("SELECT seq,run,kind,payload FROM inquiry_events WHERE kind IN ('inquiry_question','question_parent','question_evidence') ORDER BY seq"):
            data=json.loads(payload)
            if story is None or data['story']==story:values.append({'event':event,'run':run,'kind':kind,**data})
        return values

    def apply(self,q,action,*,revises_link=None,revision_reason=None):
        validate_action(action)
        start=self.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='start' ORDER BY seq LIMIT 1",(q.run,)).fetchone()
        identity=json.loads(start[0]) if start else {}
        if not start or identity.get('story',q.run)!=q.story or bool(identity.get('synthetic',True)) is not q.synthetic:
            raise QuestionMapError('question-map run/story identity mismatch')
        existing=self.events(q.story)
        if revises_link is not None:
            old=next((e for e in existing if e['event']==revises_link and e['kind']=='question_evidence'),None)
            if old is None or self.knowledge.dependencies.status(revises_link)['state']=='superseded':raise QuestionMapError('invalid relation revision target')
            if q.dependencies._synthetic(revises_link) is not q.synthetic:raise QuestionMapError('relation revision identity mismatch')
            if action['questions'] or len(action['links'])!=1 or action['links'][0]['question']!=old['question']:raise QuestionMapError('relation review cannot move question frame')
            if not isinstance(revision_reason,str) or not revision_reason.strip():raise QuestionMapError('relation revision needs reason')
        nodes={e['event']:e for e in existing if e['kind']=='inquiry_question'}
        by_text={' '.join(e['text'].split()):e['event'] for e in nodes.values()}
        local={}
        for item in action['questions']:
            old=item['revises'];value='new:'+item['key']
            if old is None:value=by_text.get(' '.join(item['text'].split()),value)
            else:
                if q.dependencies._synthetic(old) is not q.synthetic:raise QuestionMapError('question revision identity mismatch')
                replaced=self.db.execute('SELECT new_event FROM inquiry_revisions WHERE old_event=?',(old,)).fetchone()
                if replaced:
                    previous=nodes.get(replaced[0])
                    if previous is None or any(previous[k]!=item[k] for k in ('text','origin_event','origin_quote')):raise QuestionMapError('question revision target already replaced')
                    value=replaced[0]
            local[item['key']]=value
        def resolve(ref):
            if isinstance(ref,str):
                if ref not in local:raise QuestionMapError('unknown local question key')
                value=local[ref]
            else:
                if ref not in nodes or ref not in q.visible_source_text:raise QuestionMapError('unseen question or different story')
                value=ref
            if type(value) is int and self.knowledge.dependencies.status(value)['state']=='superseded':raise QuestionMapError('superseded question target or parent')
            return value
        def anchor(event,quote):
            if event not in q.visible_source_text or quote not in q.visible_source_text[event]:raise QuestionMapError('unseen question-map anchor')
            source=self.knowledge.source(event)
            if quote not in source['text'] or source['kind'] not in {'user','tool_result','knowledge_proposal','reflection','epistemic_check'}:raise QuestionMapError('invalid question-map source')
            if source['dependency_status']['state']=='superseded':raise QuestionMapError('superseded question-map source')
            if not q.synthetic and q.dependencies._synthetic(event):raise QuestionMapError('synthetic question-map source')
            return source
        edges={(e['parent'],e['child']) for e in existing if e['kind']=='question_parent'}
        proposed=[]
        revisions=[]
        for item in action['questions']:
            origin=anchor(item['origin_event'],item['origin_quote'])
            if not item['parents'] and (origin['kind']!='user' or item['origin_event'] not in q.user_sources):raise QuestionMapError('root question needs current-story user origin')
            child=local[item['key']]
            for parent in item['parents']:proposed.append((resolve(parent),child))
            old=item['revises']
            if old is not None:
                if old not in nodes or old not in q.visible_source_text:raise QuestionMapError('unseen question revision target')
                if child==old or type(child) is int and child<=old:raise QuestionMapError('question revision must be later and distinct')
                replaced=self.db.execute('SELECT new_event FROM inquiry_revisions WHERE old_event=?',(old,)).fetchone()
                if replaced and replaced[0]!=child:raise QuestionMapError('question revision target already replaced')
                if item['origin_event']==old or q.dependencies.depends_on(item['origin_event'],old,include_execution_context=False):raise QuestionMapError('question revision depends on withdrawn frame')
                revisions.append((old,child))
        edges.update(proposed)
        adjacency={}
        for parent,child in edges:adjacency.setdefault(parent,set()).add(child)
        degree={node:0 for edge in edges for node in edge}
        for parent,child in edges:degree[child]+=1
        ready=[node for node,count in degree.items() if count==0];visited=0
        while ready:
            node=ready.pop();visited+=1
            for child in adjacency.get(node,()):
                degree[child]-=1
                if degree[child]==0:ready.append(child)
        if visited!=len(degree):raise QuestionMapError('question organization cycle')
        for old,new in revisions:
            todo=[old];seen=set()
            while todo:
                node=todo.pop()
                if node==new:raise QuestionMapError('replacement question is inside old organization branch')
                if node not in seen:seen.add(node);todo.extend(adjacency.get(node,()))
        checked=[]
        for link in action['links']:
            target=resolve(link['question']);source=anchor(link['source_event'],link['quote']);claim=link['proposition']
            if claim is not None:
                if claim not in q.visible_source_text or self.knowledge.source(claim)['kind']!='knowledge_proposal':raise QuestionMapError('unseen candidate proposition')
                if self.knowledge.source(claim)['dependency_status']['state']=='superseded':raise QuestionMapError('superseded candidate proposition')
                if not q.synthetic and q.dependencies._synthetic(claim):raise QuestionMapError('synthetic candidate proposition')
            if link['relation']!='context':
                error=link_provenance_error(self.knowledge,q.dependencies,source,link['quote'],claim)
                if error is not None:raise QuestionMapError(error)
            checked.append((target,link))
        if revises_link is not None:
            for target,link in checked:
                for premise in (target,link['source_event'],link['proposition']):
                    if premise is not None and (premise==revises_link or q.dependencies.depends_on(premise,revises_link,include_execution_context=False)):raise QuestionMapError('relation replacement depends on withdrawn relation')
        # Validate the whole batch before writing. q.record/dependency.link commit
        # independently, so use direct inserts to make these local changes atomic.
        def insert(kind,data,premises=()):
            payload={'story':q.story,'synthetic':q.synthetic,'epistemic_status':'agent_organization_not_truth_verdict',**data}
            event=self.db.execute('INSERT INTO inquiry_events(run,kind,payload,at) VALUES(?,?,?,?)',(q.run,kind,json.dumps(payload,ensure_ascii=False),datetime.now(timezone.utc).isoformat())).lastrowid
            for premise in sorted(set(premises)):
                self.db.execute("INSERT INTO inquiry_dependencies(conclusion,premise,relation) VALUES(?,?,'context')",(event,premise))
            return event
        with self.db:
            for item in action['questions']:
                key=item['key']
                if isinstance(local[key],str):local[key]=insert('inquiry_question',{'text':item['text'],'origin_event':item['origin_event'],'origin_quote':item['origin_quote']},[item['origin_event']])
            def actual(ref):return local[ref[4:]] if isinstance(ref,str) else ref
            old_edges={(e['parent'],e['child']) for e in existing if e['kind']=='question_parent'}
            for parent,child in proposed:
                parent,child=actual(parent),actual(child)
                if (parent,child) not in old_edges:
                    insert('question_parent',{'parent':parent,'child':child,'relation':'subquestion_not_entailment'});old_edges.add((parent,child))
            for old,new in revisions:
                new=actual(new)
                self.db.execute('INSERT OR IGNORE INTO inquiry_revisions VALUES(?,?,?)',(old,new,'问题框架更新；不表示旧问题为假，子问题需按新范围复核'))
                self.db.execute("INSERT OR IGNORE INTO inquiry_review_queue(event,cause) SELECT conclusion,? FROM inquiry_dependencies WHERE premise=? AND relation!='execution_context'",(old,old))
            signatures={json.dumps({k:e[k] for k in ('question','proposition','source_event','quote','relation','explanation')},sort_keys=True,ensure_ascii=False) for e in existing if e['kind']=='question_evidence'}
            for target,link in checked:
                value={**link,'question':actual(target)};signature=json.dumps(value,sort_keys=True,ensure_ascii=False)
                if signature not in signatures or revises_link is not None:
                    replacement=insert('question_evidence',value,[value['question'],value['source_event']]+([value['proposition']] if value['proposition'] is not None else []));signatures.add(signature)
                    if revises_link is not None:
                        self.db.execute('INSERT INTO inquiry_revisions VALUES(?,?,?)',(revises_link,replacement,revision_reason))
                        self.db.execute("INSERT OR IGNORE INTO inquiry_review_queue(event,cause) SELECT conclusion,? FROM inquiry_dependencies WHERE premise=? AND relation!='execution_context'",(revises_link,revises_link))
        return {'question_keys':local,'graph':self.view(story=q.story,synthetic=q.synthetic),'scope':'问题、上下级和支持/挑战分类均为Agent提出的组织，原句锚定只证明出处，不证明蕴涵或答案正确；不自动关闭问题。'}

    def view(self,*,story=None,synthetic=False,limit=64,with_review_basis=False):
        if type(limit) is not int or not 1<=limit<=512:raise QuestionMapError('invalid question limit')
        events=[e for e in self.events(story) if synthetic or not e['synthetic']]
        all_nodes=[e for e in events if e['kind']=='inquiry_question'];nodes=all_nodes[-limit:];ids={e['event'] for e in nodes}
        parents=[e for e in events if e['kind']=='question_parent' and (e['parent'] in ids or e['child'] in ids)]
        all_evidence=[e for e in events if e['kind']=='question_evidence' and e['question'] in ids]
        evidence=all_evidence[-1024:]
        for e in evidence:
            e['dependency_status']=self.knowledge.dependencies.status(e['event'])
            e['source_epistemic_status']=self.knowledge.source(e['source_event']).get('epistemic_status')
            e['candidate']=self.knowledge.source(e['proposition']) if e['proposition'] is not None else None
            e['cited_source']=cited_source_state(self.knowledge,e['source_event'])
        needs={}
        for node in nodes:
            node['dependency_status']=self.knowledge.dependencies.status(node['event'])
            node['annotation_history']=[e for e in evidence if e['question']==node['event'] and e['dependency_status']['state']=='superseded']
            node['annotations']=[e for e in evidence if e['question']==node['event'] and e['dependency_status']['state']!='superseded']
            needs[node['event']]=node['dependency_status']['state']!='current_interpretation' or any(e['dependency_status']['state']!='current_interpretation' for e in node['annotations'])
        down={};up={};framing={n['event']:n['dependency_status']['state']!='current_interpretation' for n in nodes}
        for edge in parents:
            if edge['parent'] in ids and edge['child'] in ids:
                down.setdefault(edge['parent'],[]).append(edge['child']);up.setdefault(edge['child'],[]).append(edge['parent'])
        def reachable_changed(todo,adjacency,flags):
            seen=set()
            while todo:
                event=todo.pop()
                if event in seen:continue
                seen.add(event)
                if flags.get(event,False):return True
                todo.extend(adjacency.get(event,()))
            return False
        for node in nodes:
            node['review_needed_in_visible_subgraph']=reachable_changed([node['event']],down,needs)
            node['ancestor_framing_review_needed']=reachable_changed(list(up.get(node['event'],())),up,framing)
        # r92: `question_review` rows had no reader anywhere -- `candidates()` is
        # the only code that looked at them, and only for a digest. A basis field
        # nobody can print is still unobserved. Opt-in on purpose: the default
        # return value is fed verbatim to the model (inquiry.question_context
        # spreads each annotation), and a review's citations are history, not new
        # material for the next turn.
        if with_review_basis:
            from .question_reviews import review_basis_view
            for node in nodes:
                for annotation in node['annotation_history']+node['annotations']:
                    attempts=review_basis_view(self,annotation['event'])
                    if attempts:annotation['review_attempts']=attempts
        return {'nodes':nodes,'parents':parents,'truncated':len(all_nodes)>len(nodes) or len(all_evidence)>len(evidence),
            'status':'agent_proposed_organization_not_verified_answers','review_scope':'visible_subgraph_only'}


def graph_absence(path):
    """Why `read_graph` returned an empty graph -- or None when it did not.

    An empty `nodes` list and a missing `inquiry_events` table print the same
    JSON, so a reader cannot tell 'this file is not a dojo library' from 'this
    library holds no questions'. Three files in `docs/evidence` are the first
    case: healthy sqlite, `integrity_check` ok, but the candidate-pipeline
    schema built by `storage.Store`. r99 called them `unreadable_db` because
    `sqlite3.OperationalError` is a `DatabaseError`; they were never unreadable.

    Returns (state, sentence) with state in:
      'absent'    the path does not exist
      'not_dojo'  a readable sqlite file without `inquiry_events`
      'no_questions'  a dojo library that stores no question rows at all
      'filtered'  question rows exist but this --story/--synthetic view hides all
    Read-only. Never writes, never guesses at a size it did not measure.
    """
    path=Path(path)
    if not path.exists():return 'absent','%s 这个路径上没有文件：下面这份空图说的是「我看不到这个库」，不是「这个库里没有问题」。' % path
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'inquiry_events' not in tables:
            if tables:found='只有 %s，没有 inquiry_events。' % ', '.join(sorted(tables))
            else:found='里面没有任何表。'
            return 'not_dojo',('%s 是一个能打开的 SQLite 文件，但它不是 dojo 的探究库：%s'
                               '下面这份空图说的是「这不是那种库」，不是「这个库里没有问题」。') % (path,found)
        total=db.execute("SELECT count(*) FROM inquiry_events WHERE kind IN ('inquiry_question','question_parent','question_evidence')").fetchone()[0]
        if not total:
            return 'no_questions',('%s 是 dojo 的探究库，但里面一条问题记录都没有（inquiry_events 共 %d 行，没有 inquiry_question）。'
                                   '下面这份空图说的是「这个库还没记过问题」。') % (path,db.execute('SELECT count(*) FROM inquiry_events').fetchone()[0])
    finally:db.close()
    return 'filtered',('%s 里有 %d 条问题记录，但这一次的 --story / --synthetic 视图把它们全排除了：'
                       '下面这份空图说的是「这次没让你看」，不是「库里没有」。') % (path,total)


def read_graph(path,*,story=None,synthetic=False,limit=64,with_review_basis=False):
    if type(limit) is not int or not 1<=limit<=512:raise QuestionMapError('invalid question limit')
    path=Path(path)
    empty={'nodes':[],'parents':[],'truncated':False,'status':'agent_proposed_organization_not_verified_answers','review_scope':'visible_subgraph_only'}
    if not path.exists():return empty
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        if not run_index(db):return empty
        if not db.execute("SELECT 1 FROM inquiry_events WHERE kind='inquiry_question' LIMIT 1").fetchone():return empty
        return Questions(db,Knowledge(db,initialize=False)).view(story=story,synthetic=synthetic,limit=limit,with_review_basis=with_review_basis)
    finally:db.close()
