"""Remove adjacent-slice joins from an existing static Pup execution plan."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct

from codegen import TARGETS, alias_root, fold_adjacent_joins, graph_nodes, place_joins
from fuse import leaf


def compact(inventory, directory, output, backend):
    directory=Path(directory).resolve();output=Path(output).resolve()
    if directory==output: raise ValueError('choose a separate output directory')
    metadata=json.loads((directory/'plan.json').read_text());nodes=graph_nodes(inventory)
    fingerprint=hashlib.sha256(inventory).hexdigest();count=len(nodes)
    if metadata['fingerprint']!=fingerprint or metadata['nodes']!=count: raise ValueError('candidate graph differs')
    if metadata.get('backend',backend)!=backend: raise ValueError('selected plan backend differs')
    raw=(directory/f'plan-{fingerprint}.bin').read_bytes()
    if len(raw)!=80+count*128 or raw[:80]!=struct.pack('<8sQ64s',b'PPLN0001',count,fingerprint.encode()): raise ValueError('invalid candidate plan')
    aliases={};skip=set()
    for i in range(count):
        at=80+i*128;target,offset=struct.unpack_from('<QQ',raw,at+112)
        if target:
            if target>count or offset%4: raise ValueError('invalid tensor placement')
            aliases[i]=(target-1,offset)
        if struct.unpack_from('<Q',raw,at+96)[0]: skip.add(i)
    placed=place_joins(nodes,aliases,skip);folded=fold_adjacent_joins(nodes,aliases,skip);eliminated=set(placed+folded);data=bytearray(raw)
    for i in range(count):
        at=80+i*128
        if i in eliminated: data[at:at+64]=bytes(64);struct.pack_into('<Q',data,at+96,1)
        if i in aliases:
            target,offset=alias_root(i,aliases)
            if offset<0 or offset+math.prod(nodes[i]['shape'])*4>math.prod(nodes[target]['shape'])*4: raise ValueError('tensor placement exceeds destination')
            struct.pack_into('<QQ',data,at+112,target+1,offset)
    output.mkdir(parents=True,exist_ok=True)
    families=json.loads((directory/'kernels.json').read_text())
    for name in families: shutil.copyfile(directory/leaf(name),output/name)
    (output/'kernels.json').write_text(json.dumps(families,indent=2)+'\n')
    schedule=[row for row in metadata['schedule'] if row['index'] not in skip]
    suffix='.'+TARGETS[backend][1]
    for row in schedule:
        name=leaf(row['kernel']);flags=struct.unpack_from('<Q',data,80+row['index']*128+104)[0]
        for extension in (suffix,'.flex'):
            source=directory/(name+extension)
            if source.exists(): shutil.copyfile(source,output/source.name)
            if flags&4:
                source=directory/(name+'-input'+extension)
                if source.exists(): shutil.copyfile(source,output/source.name)
    if metadata['mathMode']=='fp32-tc': shutil.copyfile(directory/('pack'+suffix),output/('pack'+suffix))
    metadata=dict(metadata,backend=backend,joinedViews=metadata.get('joinedViews',0)+len(folded),destinationJoinsAdded=metadata.get('destinationJoinsAdded',0)+len(placed),placements=len(aliases),schedule=schedule,
                  launches=len(schedule),kernels=len({row['kernel'] for row in schedule}))
    (output/'plan.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (output/f'plan-{fingerprint}.bin').write_bytes(data)
    report=dict(candidate=str(directory),planSha256=hashlib.sha256(raw).hexdigest(),folded=folded,placed=placed,
                bytesNoLongerCopied=sum(math.prod(nodes[i]['shape'])*4 for i in eliminated))
    (output/'compaction.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(backend=backend,joinedViews=len(folded),placedJoins=len(placed),launches=len(schedule),output=str(output))),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory',type=Path)
    parser.add_argument('--candidate',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--backend',choices=TARGETS,required=True)
    args=parser.parse_args()
    compact(args.inventory.read_bytes(),args.candidate,args.output,args.backend)


if __name__=='__main__':
    main()
