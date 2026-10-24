"""Residual epilogue fusion preserves outputs and graph dependency boundaries."""
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'flex/ml'))
from codegen import compile_plan
from fuse import fuse
from flex.tests.vision import checkpoint


def main():
    compiler=os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler'))
    backends=os.environ.get('PUPPYBOT_TEST_BACKENDS','').split()
    checks=0
    with tempfile.TemporaryDirectory(prefix='puppybot-residual-') as temporary:
        for case in ('plain','first','silu','delayed','shared','broadcast','matmul'):
            directory=Path(temporary)/case;directory.mkdir()
            shape=[1,2,4,4] if case=='matmul' else [1,4,4,4]
            source=f'x=input("observation",{shape})\n'
            residual='r=x*.125\n' if case!='broadcast' else 'v=slice(x,1,0,1)\nr=v*.125\n'
            conv='t=permute(x,[0,1,3,2])\nc=batch_matmul(x,t)\n' if case=='matmul' else 'c=conv2d(x,"filter",4,3,1,1,1,2)\n'
            source+=conv+residual if case=='delayed' else residual+conv
            source+='s=sigmoid(c)\na=c*s\n' if case in ('silu','delayed','shared') else 'a=c\n'
            source+='y=r+a\n' if case=='first' else 'y=a+r\n'
            source+='output a,y\n' if case=='shared' else 'output y\n'
            (directory/'model.pup').write_text(source)
            factory=directory/'factory.flex'
            subprocess.run([str(ROOT/'build/flex/compile-pup'),str(directory/'model.pup'),str(factory)],check=True)
            x=[(i*7%31-15)/32 for i in range(math.prod(shape))]
            w=[(i*3%17-8)/64 for i in range(4*2*3*3)];bias=[(i-2)/16 for i in range(4)]
            checkpoint(directory,[('filter.weight',[4,2,3,3],w),('filter.bias',[4],bias)])
            sha=json.loads((directory/'model.json').read_text())['weightsSha256']
            (directory/'input.bin').write_bytes(struct.pack('<'+'f'*len(x),*x))
            host=directory/'host.flex';binary=directory/'host'
            host.write_text(f'''import "{ROOT}/flex/ml/runtime.flex";
import "{factory}";
fn main(argc,argv) {{pl_init();if argc==2 {{vp_init(".",0,0);vp_compile_only=1;pup_build_model();let data=vp_plan_inventory();return pl_atomic_file(load64(argv+8),data,load64(vp_nodes)*224);}}
vp_init(load64(argv+16),vp_backend_parse(load64(argv+8)),0);vp_checkpoint_open("{directory}/weights.bin","{sha}");pup_build_model();let data=alloc(4096);vp_require(pl_read_file("{directory}/input.bin",data,4096)==load64(vp_input+8)*4,"input length");vp_upload(load64(vp_input),data,load64(vp_input+8)*4);vp_execute();let i=0;let bytes=0;while i<load64(vp_outputs) {{let t=vp_at(vp_outputs,i);vp_read_tensor(t,data+bytes);bytes=bytes+load64(t+8)*4;i=i+1;}}return pl_atomic_file(load64(argv+24),data,bytes);}}
''')
            subprocess.run([compiler,str(host),'-o',str(binary)],check=True)
            inventory=directory/'graph.bin';subprocess.run([str(binary),str(inventory)],check=True)
            saved={}
            for fused in (False,True):
                kernels=directory/str(fused);kernels.mkdir()
                for path in (ROOT/'build/flex/pup-kernels').iterdir():
                    if path.suffix in ('.ptx','.cubin','.hip') or path.name=='kernels.json':shutil.copyfile(path,kernels/path.name)
                compile_plan(inventory.read_bytes(),kernels,compiler,['sass','cuda','hip'],patch_tiles=True,unroll=9,residual_fusion=fused)
                metadata=json.loads((kernels/'plan.json').read_text())
                assert metadata['residuals']==int(fused and case not in ('delayed','shared','broadcast'));checks+=1
                for backend in ['cpu',*backends]:
                    output=directory/'output.bin'
                    subprocess.run([str(binary),backend,str(kernels),str(output)],check=True,timeout=30)
                    data=output.read_bytes();values=struct.unpack('<'+'f'*(len(data)//4),data)
                    if not fused:saved[backend]=data
                    else:assert data==saved[backend],(case,backend,'fusion changed output')
                    reference=struct.unpack('<'+'f'*(len(saved['cpu'])//4),saved['cpu'])
                    assert len(values)==len(reference)
                    for actual,expected in zip(values,reference):
                        assert math.isclose(actual,expected,rel_tol=2e-5,abs_tol=2e-6),(case,backend,actual,expected)
                        checks+=1
            for backend in backends:
                selected=directory/('selected-'+backend)
                fuse(inventory.read_bytes(),directory/'False',selected,compiler,backend)
                metadata=json.loads((selected/'plan.json').read_text())
                assert metadata['residuals']==int(case not in ('delayed','shared','broadcast'));checks+=1
                subprocess.run([str(binary),backend,str(selected),str(output)],check=True,timeout=30)
                assert output.read_bytes()==saved[backend],(case,backend,'selected fusion changed output')
                checks+=len(saved[backend])//4
    print(f'Pup residual fusion: {checks} output and dependency checks passed')


if __name__=='__main__':
    main()
