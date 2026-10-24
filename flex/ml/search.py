"""Confirm profile-guided kernel substitutions with complete resident inference."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess

from tune import candidate, select


def identity(plan, index, backend):
    entry=plan['data'][80+index*128:80+(index+1)*128]
    name=entry[:64].split(b'\0',1)[0].decode();suffix='.cubin' if backend=='sass' else '.ptx'
    data=(plan['directory']/(name+suffix)).read_bytes();data=struct.pack('<Q',len(data))+data+entry[64:112]
    if struct.unpack_from('<Q',entry,104)[0]&4:data+=(plan['directory']/(name+'-input'+suffix)).read_bytes()
    return hashlib.sha256(data).hexdigest()


def percentile(values, fraction):
    ordered=sorted(values);at=(len(values)-1)*fraction;lo=int(at);hi=min(lo+1,len(ordered)-1)
    return ordered[lo]+(ordered[hi]-ordered[lo])*(at-lo)


def measure(binary, backend, directory, weights, sha, inputs, output, timeout, reference=None):
    args=[str(binary),backend,str(directory),str(weights),sha,str(output),*[str(path) for path in inputs]]
    result=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if result.returncode:raise ValueError('benchmark failed: '+result.stderr[-2000:])
    samples=json.loads(result.stdout)
    if not isinstance(samples,list) or len(samples)<3 or any(type(v)!=int or v<=0 for v in samples):raise ValueError('invalid benchmark samples')
    data=output.read_bytes()
    if not data or len(data)%4:raise ValueError('invalid benchmark output size')
    if reference is not None:
        if data!=reference:raise ValueError('benchmark output differs from baseline')
    elif any(not math.isfinite(v[0]) for v in struct.iter_unpack('<f',data)):raise ValueError('nonfinite baseline output')
    return dict(samplesNs=samples,medianNs=percentile(samples,.5),p10Ns=percentile(samples,.1),outputSha256=hashlib.sha256(data).hexdigest())


def search(candidates, output, backend, binary, weights, sha, inputs, trials=32, alternatives=2, minimum_gain=.001, timeout=120):
    output=Path(output).resolve();directory=output/'plan';directory.mkdir(parents=True,exist_ok=True)
    if any(output==c['directory'] or directory==c['directory'] for c in candidates):raise ValueError('choose a separate output directory')
    choices={};baseline=candidates[0]
    select(candidates,directory,backend,0,choices=choices,quiet=True)
    result=measure(binary,backend,directory,weights,sha,inputs,output/'reference.bin',timeout)
    reference=(output/'reference.bin').read_bytes()
    proposals=[]
    for index in baseline['times']:
        seen={identity(baseline,index,backend)};options=[]
        for plan in sorted(candidates[1:],key=lambda c:c['times'].get(index,float('inf'))):
            value=plan['times'].get(index,float('inf'))
            if value>=baseline['times'][index]*.95:continue
            key=identity(plan,index,backend)
            if key in seen:continue
            seen.add(key);options.append((baseline['times'][index]-value,index,plan))
        proposals+=options[:alternatives]
    proposals.sort(key=lambda row:row[0],reverse=True)
    report=dict(backend=backend,benchmarkSha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),weightsSha256=sha,
                inputSha256=[hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in inputs],
                baseline=result,verification='all output bytes equal baseline',minimumGain=minimum_gain,trials=[])
    output_path=output/'trial-output.bin'
    for _,index,plan in proposals[:trials]:
        previous=choices.get(index,baseline)
        if identity(previous,index,backend)==identity(plan,index,backend):continue
        row=dict(index=index,candidate=str(plan['directory']),accepted=False)
        try:
            before=measure(binary,backend,directory,weights,sha,inputs,output_path,timeout,reference)
            trial=dict(choices);trial[index]=plan;select(candidates,directory,backend,0,choices=trial,quiet=True)
            first=measure(binary,backend,directory,weights,sha,inputs,output_path,timeout,reference)
            row.update(before=before,first=first)
            if first['medianNs']<before['medianNs']*(1-minimum_gain) and first['p10Ns']<before['p10Ns']:
                second=measure(binary,backend,directory,weights,sha,inputs,output_path,timeout,reference)
                select(candidates,directory,backend,0,choices=choices,quiet=True)
                after=measure(binary,backend,directory,weights,sha,inputs,output_path,timeout,reference)
                row.update(second=second,after=after)
                old=(before['medianNs']+after['medianNs'])/2;new=(first['medianNs']+second['medianNs'])/2
                if second['medianNs']<after['medianNs'] and second['p10Ns']<after['p10Ns'] and new<old*(1-minimum_gain):choices=trial;row['accepted']=True
        except (ValueError,subprocess.TimeoutExpired) as error:
            row['rejection']=str(error)
        finally:
            select(candidates,directory,backend,0,choices=choices,quiet=True)
        report['trials'].append(row)
        (output/'search.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(dict(index=index,candidate=Path(plan['directory']).name,accepted=row['accepted'],rejection=row.get('rejection'),medianMs=row.get('first',{}).get('medianNs',0)/1e6)),flush=True)
    report['final']=measure(binary,backend,directory,weights,sha,inputs,output_path,timeout,reference)
    report['selected']={str(index):str(plan['directory']) for index,plan in choices.items()}
    (output/'search.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(output=str(directory),accepted=len(choices),baselineMs=report['baseline']['medianNs']/1e6,finalMs=report['final']['medianNs']/1e6)),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',nargs=2,action='append',required=True,metavar=('DIRECTORY','PROFILE'))
    parser.add_argument('--backend',choices=['sass','cuda'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--benchmark',type=Path,required=True)
    parser.add_argument('--weights',type=Path,required=True)
    parser.add_argument('--weights-sha256',required=True)
    parser.add_argument('--input',type=Path,action='append',required=True)
    parser.add_argument('--trials',type=int,default=32)
    parser.add_argument('--alternatives',type=int,default=2)
    parser.add_argument('--minimum-gain',type=float,default=.001)
    args=parser.parse_args()
    if args.trials<1 or args.alternatives<1 or not 0<=args.minimum_gain<1:parser.error('invalid search bounds')
    search([candidate(*paths,args.backend) for paths in args.candidate],args.output,args.backend,args.benchmark,
           args.weights,args.weights_sha256,args.input,args.trials,args.alternatives,args.minimum_gain)


if __name__=='__main__':
    main()
