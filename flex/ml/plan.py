"""Graph metadata helpers for profile and artifact tools; kernel lowering is native."""
from collections import defaultdict
import math
import struct

TARGETS = {'sass': ('sass-sm75', 'cubin'), 'cuda': ('ptx', 'ptx'), 'hip': ('hip', 'hip')}


def graph_nodes(inventory):
    rows = list(struct.iter_unpack('<28q',inventory))
    nodes = [dict(op=r[0],shape=r[8:12],a=r[12:16],b=r[16:20],params=r[20:24],left=r[24],right=r[25],bias=r[26],output=r[27]) for r in rows]
    return nodes


def graph_fusions(nodes, residual_fusion):
    users=defaultdict(list)
    for i,node in enumerate(nodes):
        for key in ('left','right'):
            if node[key]>=0: users[node[key]].append(i)
    fused={}; skip=set()
    for i,node in enumerate(nodes):
        if node['op']!=12 or node['output']: continue
        sigmoid=[j for j in users[i] if nodes[j]['op']==24 and not nodes[j]['output']]
        if len(sigmoid)!=1: continue
        s=sigmoid[0]
        if len(users[s])!=1: continue
        j=users[s][0]
        if nodes[j]['op']==5 and set((nodes[j]['left'],nodes[j]['right']))=={i,s} and set(users[i])=={s,j}:
            fused[i]=j; skip.update((s,j))
    activations=set(fused);residuals={}
    if residual_fusion:
        producers={i:i for i,node in enumerate(nodes) if node['op'] in (12,29) and not node['output']}
        producers.update({target:producer for producer,target in fused.items()})
        for i,node in enumerate(nodes):
            if node['op']!=3: continue
            for key,other_key in (('left','right'),('right','left')):
                target=node[key];producer=producers.get(target);other=node[other_key]
                if producer is None or other<0 or other>=producer: continue
                if nodes[target]['output'] or users[target]!=[i]: continue
                if node['shape']!=node['a'] or node['shape']!=node['b']: continue
                if math.prod(node['shape'])!=math.prod(nodes[producer]['shape']): continue
                residuals[producer]=(other,other_key=='left');fused[producer]=i;skip.add(i);break
    return users,fused,activations,residuals,skip


def alias_root(index, aliases):
    offset=0;seen=set()
    while index in aliases:
        if index in seen: raise ValueError('cyclic tensor placement')
        seen.add(index);index,step=aliases[index];offset+=step
    return index,offset


def fold_adjacent_joins(nodes, aliases, skip):
    folded=[];changed=True
    while changed:
        changed=False
        for i,node in enumerate(nodes):
            if i in skip or node['op']!=25 or math.prod(node['shape'][:node['params'][0]])!=1: continue
            if node['left']<0 or node['right']<0: continue
            base,left=alias_root(node['left'],aliases);other,right=alias_root(node['right'],aliases)
            if base!=other or left+math.prod(node['a'])*4!=right: continue
            target,offset=alias_root(i,aliases)
            if (base,left)!=(target,offset):
                # Relocate the complete source into this join's existing
                # destination. Its slice views must follow that placement.
                # A partial source could overwrite neighboring destination data.
                if base==target or left or math.prod(node['shape'])!=math.prod(nodes[base]['shape']): continue
                aliases[base]=(target,offset)
            skip.add(i);folded.append(i);changed=True
    return folded


def place_joins(nodes, aliases, skip, exclusive=False):
    users=defaultdict(list)
    if exclusive:
        for i,node in enumerate(nodes):
            for key in ('left','right'):
                if node[key]>=0: users[node[key]].append(i)
    placed=[]
    for i,node in reversed(list(enumerate(nodes))):
        if i in skip or node['op']!=25 or math.prod(node['shape'][:node['params'][0]])!=1: continue
        parents=(node['left'],node['right'])
        if any(parent<0 for parent in parents): continue
        if exclusive and any(len(users[parent])!=1 or nodes[parent]['output'] for parent in parents): continue
        target,offset=alias_root(i,aliases);pending={};valid=True
        for parent,step,shape in ((parents[0],0,node['a']),(parents[1],math.prod(node['a'])*4,node['b'])):
            desired=(target,offset+step)
            if alias_root(parent,aliases)==desired: continue
            # A tensor has one physical destination. Existing views and prior
            # placements cannot be redirected to satisfy a second join.
            if parent in aliases or parent==target or math.prod(nodes[parent]['shape'])!=math.prod(shape):valid=False;break
            if parent in pending and pending[parent]!=desired:valid=False;break
            pending[parent]=desired
        if valid:
            aliases.update(pending);skip.add(i);placed.append(i)
    return placed
