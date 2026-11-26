"""Finite transition-graph progress checks; model completeness is unverified."""
from collections import deque
from graphlib import CycleError,TopologicalSorter


def validate_action(action):
    expected={'kind','states','initial','goals','transitions','assumptions','prediction'}
    if not isinstance(action,dict) or set(action)!=expected or action['kind']!='check_progress':raise ValueError('invalid progress action fields')
    states=action['states']
    if not isinstance(states,dict) or not 1<=len(states)<=32:raise ValueError('progress model needs 1..32 states')
    for key,description in states.items():
        if not isinstance(key,str) or not key.strip() or len(key)>80:raise ValueError('invalid state identifier')
        if not isinstance(description,str) or not description.strip() or len(description)>500:raise ValueError('invalid state description')
    if not isinstance(action['initial'],str) or action['initial'] not in states:raise ValueError('unknown initial state')
    goals=action['goals']
    if not isinstance(goals,list) or not 1<=len(goals)<=32 or any(not isinstance(s,str) or s not in states for s in goals) or len(set(goals))!=len(goals):raise ValueError('invalid goal states')
    edges=action['transitions']
    if not isinstance(edges,list) or len(edges)>128:raise ValueError('at most 128 transitions are allowed')
    for edge in edges:
        if not isinstance(edge,dict) or set(edge)!={'source','target','label'}:raise ValueError('invalid transition fields')
        if any(not isinstance(edge[k],str) or edge[k] not in states for k in ('source','target')):raise ValueError('unknown transition state')
        if not isinstance(edge['label'],str) or not edge['label'].strip() or len(edge['label'])>160:raise ValueError('invalid transition label')
    if not isinstance(action['assumptions'],list) or not 1<=len(action['assumptions'])<=12 or any(not isinstance(s,str) or not s.strip() or len(s)>2000 for s in action['assumptions']):raise ValueError('explicit progress assumptions required')
    if not isinstance(action['prediction'],str) or not action['prediction'].strip() or len(action['prediction'])>2000:raise ValueError('progress prediction required')


def check(action):
    validate_action(action)
    initial=action['initial'];goals=set(action['goals'])
    outgoing={s:set() for s in action['states']}
    for edge in action['transitions']:outgoing[edge['source']].add(edge['target'])
    parents={initial:None};queue=deque([initial]);order=[]
    # The property concerns first reaching a goal, not behavior thereafter.
    while queue:
        state=queue.popleft();order.append(state)
        if state in goals:continue
        for target in sorted(outgoing[state]):
            if target not in parents:parents[target]=state;queue.append(target)
    def path(state):
        result=[]
        while state is not None:result.append(state);state=parents[state]
        return list(reversed(result))
    reached_goals=[s for s in order if s in goals]
    nong=[s for s in order if s not in goals]
    result=dict(all_paths_reach_goal=False,goal_reachable=bool(reached_goals),
                reachable_before_first_goal=order,goal_path=path(reached_goals[0]) if reached_goals else None,
                counterexample=None,rank=None,max_transitions_to_goal=None,
                scope='Only maximal paths in the supplied finite transition graph until first reaching a declared goal are checked. No fairness, wall-time, human behavior, semantic novelty, model completeness, goal quality or behavior after the first goal is certified. Encode possible indefinite waiting as a non-goal cycle; transition labels and state meanings are assumptions, not measured events.')
    deadlock=next((s for s in nong if not outgoing[s]),None)
    if deadlock is not None:
        result.update(status='may_stall',counterexample={'kind':'deadlock','prefix':path(deadlock),'cycle':None})
        return result
    predecessors={s:set() for s in nong}
    for source in nong:
        for target in outgoing[source]:
            if target in predecessors:predecessors[target].add(source)
    try:topological=list(TopologicalSorter({s:sorted(p) for s,p in predecessors.items()}).static_order())
    except CycleError as error:
        cycle=error.args[1]
        result.update(status='may_stall',counterexample={'kind':'cycle','prefix':path(cycle[0]),'cycle':cycle})
        return result
    rank={s:0 for s in reached_goals}
    for state in reversed(topological):rank[state]=1+max(rank[target] for target in outgoing[state])
    result.update(status='all_paths_reach_goal',all_paths_reach_goal=True,rank=rank,max_transitions_to_goal=rank[initial])
    return result
