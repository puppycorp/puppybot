"""Fuse residual additions into a measured FP32 Pup plan's selected kernels."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

from codegen import TARGETS, graph_fusions, graph_nodes, residual_epilogue


def leaf(name):
    if not name or Path(name).name!=name: raise ValueError('invalid kernel file name')
    return name


def fuse(inventory, directory, output, compiler, backend):
    directory=Path(directory).resolve();output=Path(output).resolve()
    if output==directory: raise ValueError('choose a separate output directory')
    metadata=json.loads((directory/'plan.json').read_text())
    if metadata['mathMode']!='fp32': raise ValueError('residual fusion requires an FP32 plan')
    if metadata.get('backend',backend)!=backend: raise ValueError('selected plan backend differs')
    fingerprint=hashlib.sha256(inventory).hexdigest()
    if metadata['fingerprint']!=fingerprint: raise ValueError('candidate graph differs')
    nodes=graph_nodes(inventory);count=len(nodes)
    raw=(directory/f'plan-{fingerprint}.bin').read_bytes()
    header=struct.pack('<8sQ64s',b'PPLN0001',count,fingerprint.encode())
    if len(raw)!=80+count*128 or raw[:80]!=header: raise ValueError('invalid candidate plan')
    _,original,_,_,_=graph_fusions(nodes,False)
    _,fused,_,residuals,_=graph_fusions(nodes,True)
    for i in range(count):
        at=80+i*128;flags=struct.unpack_from('<Q',raw,at+104)[0]
        if flags&~4: raise ValueError('candidate has unsupported epilogue flags')
        if i in residuals:
            target,skip=struct.unpack_from('<Q',raw,at+64)[0],struct.unpack_from('<Q',raw,at+96)[0]
            if target!=original.get(i,i) or skip: raise ValueError('candidate epilogue differs')
            if struct.unpack_from('<Q',raw,80+fused[i]*128+96)[0]: raise ValueError('residual addition already skipped')
    output.mkdir(parents=True,exist_ok=True)
    families=json.loads((directory/'kernels.json').read_text())
    for name in families: shutil.copyfile(directory/leaf(name),output/name)
    (output/'kernels.json').write_text(json.dumps(families,indent=2)+'\n')
    target,suffix=TARGETS[backend];extension='.'+suffix;data=bytearray(raw)
    additions={fused[i] for i in residuals};schedule=[];changes=[]
    for row in metadata['schedule']:
        i=row['index'];at=80+i*128
        if i in additions:
            data[at:at+64]=bytes(64);struct.pack_into('<Q',data,at+96,1);continue
        name=leaf(row['kernel']);flags=struct.unpack_from('<Q',raw,at+104)[0]
        if i in residuals:
            source=(directory/(name+'.flex')).read_text()
            start=source.index('{',source.index('fn kernel('))+1;end=source.index('\nreturn 0;}',start)
            source=source[:start]+residual_epilogue(source[start:end],residuals[i][1])+source[end:]
            text=source.encode();identity=struct.pack('<Q',len(text))+text
            if flags&4: identity+=(directory/(name+'-input'+extension)).read_bytes()
            renamed='k'+hashlib.sha256(identity).hexdigest()[:24]
            path=output/(renamed+'.flex');path.write_text(source)
            subprocess.run([str(compiler),'--target',target,str(path),'-o',str(output/(renamed+extension))],check=True)
            if flags&4:
                for ext in (extension,'.flex'):
                    source_path=directory/(name+'-input'+ext)
                    if source_path.exists(): shutil.copyfile(source_path,output/(renamed+'-input'+ext))
            flags|=8|((residuals[i][0]+1)<<32)
            data[at:at+64]=struct.pack('<64s',renamed.encode());struct.pack_into('<Q',data,at+64,fused[i]);struct.pack_into('<Q',data,at+104,flags)
            changes.append(dict(index=i,output=fused[i],residual=residuals[i][0],residualFirst=residuals[i][1],kernel=renamed))
            row=dict(row,kernel=renamed)
        else:
            for ext in (extension,'.flex'):
                shutil.copyfile(directory/(name+ext),output/(name+ext))
                if flags&4:
                    source_path=directory/(name+'-input'+ext)
                    if source_path.exists(): shutil.copyfile(source_path,output/(name+'-input'+ext))
        schedule.append(row)
    metadata=dict(metadata,backend=backend,residuals=len(changes),schedule=schedule,
                  launches=len(schedule),kernels=len({row['kernel'] for row in schedule}))
    (output/'plan.json').write_text(json.dumps(metadata,indent=2)+'\n')
    (output/f'plan-{fingerprint}.bin').write_bytes(data)
    report=dict(candidate=str(directory),planSha256=hashlib.sha256(raw).hexdigest(),
                compilerSha256=hashlib.sha256(Path(compiler).read_bytes()).hexdigest(),changes=changes)
    (output/'fusion.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(backend=backend,residuals=len(changes),launches=len(schedule),output=str(output))),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory',type=Path)
    parser.add_argument('--candidate',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--compiler',required=True,type=Path)
    parser.add_argument('--backend',choices=TARGETS,required=True)
    args=parser.parse_args()
    fuse(args.inventory.read_bytes(),args.candidate,args.output,args.compiler,args.backend)


if __name__=='__main__':
    main()
