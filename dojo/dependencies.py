"""Versioned dependency index over inquiry events, never a truth score.

Edges mean that an interpretation USED a context item, not that it follows logically.
Revisions enqueue review work; bounded queue draining never rewrites conclusions.
"""
import json
from .tool_schema import DETERMINISTIC_TOOLS
from collections import deque


class DependencyIndex:
    def __init__(self, connection, *, initialize=True):
        self.db=connection
        if not initialize:return
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS inquiry_dependencies (
          conclusion INTEGER NOT NULL, premise INTEGER NOT NULL,
          relation TEXT NOT NULL DEFAULT 'context',
          PRIMARY KEY(conclusion,premise), CHECK(conclusion != premise));
        CREATE INDEX IF NOT EXISTS inquiry_dependency_premises ON inquiry_dependencies(premise);
        CREATE TABLE IF NOT EXISTS inquiry_revisions (
          old_event INTEGER PRIMARY KEY, new_event INTEGER NOT NULL, reason TEXT NOT NULL,
          CHECK(old_event != new_event));
        CREATE TABLE IF NOT EXISTS inquiry_review_queue (
          event INTEGER NOT NULL, cause INTEGER NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending',
          PRIMARY KEY(event,cause));
        ''')

    def _event(self, seq):
        if type(seq) is not int: raise ValueError('event must be an integer')
        row=self.db.execute('SELECT run,kind,payload FROM inquiry_events WHERE seq=?',(seq,)).fetchone()
        if row is None: raise ValueError('unknown inquiry event')
        return row

    def _synthetic(self, seq):
        run,_,_=self._event(seq)
        row=self.db.execute("SELECT payload FROM inquiry_events WHERE run=? AND kind='start' ORDER BY seq LIMIT 1",(run,)).fetchone()
        return bool(json.loads(row[0]).get('synthetic')) if row else True

    def link(self, conclusion, premises, *, relation='context'):
        """Only older context can be a dependency, so dependency cycles are impossible."""
        _,kind,payload=self._event(conclusion)
        if relation not in {'context','execution_context'}:raise ValueError('invalid dependency relation')
        if relation=='execution_context':
            data=json.loads(payload)
            if kind!='tool_result' or data.get('status')!='executed' or data.get('action',{}).get('kind') not in DETERMINISTIC_TOOLS:raise ValueError('execution context requires a successful deterministic receipt')
        premises=sorted(set(premises))
        for premise in premises:
            self._event(premise)
            if premise>=conclusion: raise ValueError('dependency must precede conclusion')
            if not self._synthetic(conclusion) and self._synthetic(premise):
                raise ValueError('synthetic context cannot support a real inquiry')
            if relation=='execution_context' and self._event(premise)[1]!='reflection':raise ValueError('execution context must name a planning reflection')
            existing=self.db.execute('SELECT relation FROM inquiry_dependencies WHERE conclusion=? AND premise=?',(conclusion,premise)).fetchone()
            if existing and existing[0]!=relation:raise ValueError('dependency role changes require explicit revalidation')
        with self.db:
            for premise in premises:
                self.db.execute('INSERT OR IGNORE INTO inquiry_dependencies(conclusion,premise,relation) VALUES(?,?,?)',(conclusion,premise,relation))
                # A newly linked interpretation cannot silently inherit an already stale context.
                changed=self.db.execute('SELECT 1 FROM inquiry_revisions WHERE old_event=?',(premise,)).fetchone()
                stale=self.db.execute('SELECT 1 FROM inquiry_review_queue WHERE event=?',(premise,)).fetchone()
                if relation!='execution_context' and (changed or stale):
                    self.db.execute('INSERT OR IGNORE INTO inquiry_review_queue(event,cause) VALUES(?,?)',(conclusion,premise))

    def depends_on(self, conclusion, premise, *, include_execution_context=True):
        return self.db.execute('''WITH RECURSIVE ancestors(event) AS (
            SELECT premise FROM inquiry_dependencies WHERE conclusion=? AND (? OR relation!='execution_context')
            UNION SELECT d.premise FROM inquiry_dependencies d JOIN ancestors a ON d.conclusion=a.event WHERE ? OR d.relation!='execution_context')
            SELECT 1 FROM ancestors WHERE event=? LIMIT 1''',(conclusion,include_execution_context,include_execution_context,premise)).fetchone() is not None

    def revise(self, old, new, reason):
        """A new interpretation replaces the current projection; old bytes stay intact."""
        self._event(old);self._event(new)
        if new<=old or not isinstance(reason,str) or not reason.strip():raise ValueError('revision needs a later event and a reason')
        if not self._synthetic(old) and self._synthetic(new):raise ValueError('synthetic cannot revise real knowledge')
        # The replacement must not depend on the interpretation it is withdrawing.
        ancestors={new};queue=deque([new])
        while queue:
            node=queue.popleft()
            for (premise,) in self.db.execute("SELECT premise FROM inquiry_dependencies WHERE conclusion=? AND relation!='execution_context'",(node,)):
                if premise==old:raise ValueError('replacement depends on the withdrawn interpretation')
                if premise not in ancestors:ancestors.add(premise);queue.append(premise)
        with self.db:
            existing=self.db.execute('SELECT new_event,reason FROM inquiry_revisions WHERE old_event=?',(old,)).fetchone()
            if existing:
                if existing!=(new,reason):raise ValueError('revision is immutable; revise the replacement instead')
                return
            self.db.execute('INSERT INTO inquiry_revisions VALUES(?,?,?)',(old,new,reason))
            self.db.execute("INSERT OR IGNORE INTO inquiry_review_queue(event,cause) SELECT conclusion,? FROM inquiry_dependencies WHERE premise=? AND relation!='execution_context'",(old,old))

    def drain(self, budget=8):
        """At most budget queue items; diamond paths coalesce by (event,cause)."""
        if type(budget) is not int or not 0<=budget<=1000:raise ValueError('invalid review budget')
        visited=[]
        with self.db:
            for _ in range(budget):
                row=self.db.execute("SELECT event,cause FROM inquiry_review_queue WHERE state='pending' ORDER BY cause,event LIMIT 1").fetchone()
                if row is None:break
                event,cause=row
                self.db.execute("UPDATE inquiry_review_queue SET state='marked' WHERE event=? AND cause=?",row)
                self.db.execute("INSERT OR IGNORE INTO inquiry_review_queue(event,cause) SELECT conclusion,? FROM inquiry_dependencies WHERE premise=? AND relation!='execution_context'",(cause,event))
                visited.append({'event':event,'cause':cause})
        return visited

    def status(self, event):
        self._event(event)
        replacement=self.db.execute('SELECT new_event,reason FROM inquiry_revisions WHERE old_event=?',(event,)).fetchone()
        if replacement:return {'state':'superseded','replacement':replacement[0],'reason':replacement[1]}
        # Execution-context edges preserve provenance and echo detection, but a
        # fixed-input computation is not invalidated by its planning narrative.
        # Old queue entries stay auditable; ignore only causes whose EVERY path
        # crosses such a verified boundary. A second live path still invalidates.
        causes=[x[0] for x in self.db.execute('''WITH RECURSIVE
            all_ancestors(event) AS (
              SELECT premise FROM inquiry_dependencies WHERE conclusion=?
              UNION SELECT d.premise FROM inquiry_dependencies d JOIN all_ancestors a ON d.conclusion=a.event),
            ancestors(event) AS (
              SELECT premise FROM inquiry_dependencies WHERE conclusion=? AND relation!='execution_context'
              UNION SELECT d.premise FROM inquiry_dependencies d JOIN ancestors a ON d.conclusion=a.event WHERE d.relation!='execution_context')
            SELECT r.old_event FROM inquiry_revisions r JOIN ancestors a ON a.event=r.old_event
            UNION SELECT q.cause FROM inquiry_review_queue q WHERE (q.event=? OR q.event IN (SELECT event FROM ancestors)) AND
              (q.cause NOT IN (SELECT event FROM all_ancestors) OR q.cause IN (SELECT event FROM ancestors))''',(event,event,event))]
        causes=sorted(set(causes))
        return {'state':'needs_review','causes':causes} if causes else {'state':'current_interpretation','truth':'not_certified'}
