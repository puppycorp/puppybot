"""Select measured kernels for a static Pup graph without changing its math mode."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct


def candidate(directory, profile, backend, allow_unbound=False):
    directory=Path(directory).resolve()
    metadata=json.loads((directory/'plan.json').read_text())
    data=(directory/f"plan-{metadata['fingerprint']}.bin").read_bytes()
    if len(data)!=80+metadata['nodes']*128 or data[:8]!=b'PPLN0001':
        raise ValueError('invalid candidate plan')
    times={};mode=None
    plan_hash=hashlib.sha256(data).hexdigest()
    suffix='.cubin' if backend=='sass' else '.ptx'
    for line in Path(profile).read_text().splitlines():
        row=json.loads(line)
        method=row.get('mode','hot')
        if method not in ('hot','graph') or mode is not None and method!=mode: raise ValueError('profile methods differ')
        mode=method
        if not math.isfinite(row['ms']) or row['ms']<=0: raise ValueError('invalid timing')
        index=row['index']
        if type(index)!=int or index<0 or index>=metadata['nodes'] or index in times:
            raise ValueError('invalid or duplicate profile index')
        entry=data[80+index*128:80+(index+1)*128]
        if struct.unpack_from('<Q',entry,96)[0]: raise ValueError('profile includes a skipped node')
        if 'planSha256' not in row:
            if not allow_unbound: raise ValueError('profile is not bound to its plan and kernels; regenerate it with pup-profile')
        else:
            if row['planSha256']!=plan_hash or row.get('backend')!=backend:
                raise ValueError('profile plan or backend differs')
            name=entry[:64].split(b'\0',1)[0].decode()
            if not name or Path(name).name!=name: raise ValueError('invalid kernel name')
            actual=hashlib.sha256((directory/(name+suffix)).read_bytes()).hexdigest()
            if row.get('kernelSha256')!=actual: raise ValueError('profile kernel differs')
            prepare=''
            if struct.unpack_from('<Q',entry,104)[0]&4:
                prepare=hashlib.sha256((directory/(name+'-input'+suffix)).read_bytes()).hexdigest()
            if row.get('prepareSha256','')!=prepare: raise ValueError('profile preparation kernel differs')
        times[index]=row['ms']
    return dict(directory=directory,metadata=metadata,data=data,times=times,mode=mode,
                schedule={row['index']:row for row in metadata['schedule']})


def select(candidates, output, backend, minimum_gain, choices=None, quiet=False):
    baseline=candidates[0]
    output=output.resolve()
    if any(output==c['directory'] for c in candidates):
        raise ValueError('choose an output directory separate from the candidates')
    for c in candidates:
        if c['mode']!=baseline['mode']: raise ValueError('candidate profiling methods differ')
        if c['metadata']['mathMode']!=baseline['metadata']['mathMode'] or c['data'][:80]!=baseline['data'][:80]:
            raise ValueError('candidate graph or numerical mode differs')
        for index in range(baseline['metadata']['nodes']):
            at=80+index*128
            for start,end in ((64,72),(96,104),(112,128)):
                if c['data'][at+start:at+end]!=baseline['data'][at+start:at+end]:
                    raise ValueError('candidate fusion or tensor placement differs')
            if (struct.unpack_from('<Q',c['data'],at+104)[0]^struct.unpack_from('<Q',baseline['data'],at+104)[0])&0xffffffff00000008:
                raise ValueError('candidate residual dependency differs')
    suffix='.cubin' if backend=='sass' else '.ptx'
    output.mkdir(parents=True,exist_ok=True)
    families=json.loads((baseline['directory']/'kernels.json').read_text())
    for name in families:
        if Path(name).name!=name: raise ValueError('invalid kernel file name')
        shutil.copyfile(baseline['directory']/name,output/name)
    (output/'kernels.json').write_text(json.dumps(families,indent=2)+'\n')
    data=bytearray(baseline['data']);chosen=[];schedule=[]
    for index in range(baseline['metadata']['nodes']):
        at=80+index*128
        if struct.unpack_from('<Q',data,at+96)[0]: continue
        selected=baseline
        if choices is not None:
            selected=choices.get(index,baseline)
        elif index in baseline['times']:
            fastest=min(candidates,key=lambda c:c['times'].get(index,float('inf')))
            if fastest['times'].get(index,float('inf'))<baseline['times'][index]*(1-minimum_gain):
                selected=fastest
        entry=bytearray(selected['data'][at:at+128])
        name=entry[:64].split(b'\0',1)[0].decode()
        if Path(name).name!=name: raise ValueError('invalid kernel name')
        artifact=selected['directory']/(name+suffix)
        native=artifact.read_bytes();identity=struct.pack('<Q',len(native))+native
        if struct.unpack_from('<Q',entry,104)[0]&4:
            identity+=(selected['directory']/(name+'-input'+suffix)).read_bytes()
        renamed='t'+hashlib.sha256(identity).hexdigest()[:24]
        shutil.copyfile(artifact,output/(renamed+suffix))
        source=selected['directory']/(name+'.flex')
        if source.exists(): shutil.copyfile(source,output/(renamed+'.flex'))
        if struct.unpack_from('<Q',entry,104)[0]&4:
            for extension in (suffix,'.flex'):
                source=selected['directory']/(name+'-input'+extension)
                if source.exists(): shutil.copyfile(source,output/(renamed+'-input'+extension))
        entry[:64]=struct.pack('<64s',renamed.encode());data[at:at+128]=entry
        schedule.append(dict(selected['schedule'][index],kernel=renamed))
        chosen.append(dict(index=index,candidate=str(selected['directory']),kernel=renamed,
                           baselineMs=baseline['times'].get(index),selectedMs=selected['times'].get(index)))
    if baseline['metadata']['mathMode']=='fp32-tc':
        shutil.copyfile(baseline['directory']/('pack'+suffix),output/('pack'+suffix))
    metadata=dict(baseline['metadata'],backend=backend,tile=None,schedule=schedule)
    metadata['kernels']=len({row['kernel'] for row in schedule})
    (output/f"plan-{metadata['fingerprint']}.bin").write_bytes(data)
    (output/'plan.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (output/'selection.json').write_text(json.dumps(chosen,indent=2)+'\n')
    counts=Counter(Path(row['candidate']).name for row in chosen)
    if not quiet: print(json.dumps(dict(backend=backend,selected=dict(counts),output=str(output))),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',nargs=2,action='append',required=True,metavar=('DIRECTORY','PROFILE'))
    parser.add_argument('--backend',choices=['sass','cuda'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--allow-unbound-profiles',action='store_true',help='accept legacy timing files without artifact hashes')
    parser.add_argument('--minimum-gain',type=float,default=.05)
    args=parser.parse_args()
    if not 0<=args.minimum_gain<1: parser.error('minimum gain must be in [0,1)')
    select([candidate(*paths,args.backend,args.allow_unbound_profiles) for paths in args.candidate],args.output,args.backend,args.minimum_gain)


if __name__=='__main__':
    main()
