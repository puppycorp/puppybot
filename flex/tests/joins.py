"""Zero-copy joins preserve source outputs, nested views and destination placement."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'flex/ml'))
from codegen import compile_plan
from compact import compact
from flex.tests.vision import checkpoint


def main():
    compiler=os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler'))
    backends=os.environ.get('PUPPYBOT_TEST_BACKENDS','').split()
    checks=0
    with tempfile.TemporaryDirectory(prefix='puppybot-joins-') as temporary:
        for case in ('adjacent','nested','partial','reversed','gap','batch','shared','duplicate','multiple'):
            directory=Path(temporary)/case;directory.mkdir();batch=2 if case=='batch' else 1
            model=f'x=input("observation",[{batch},8,2,3])\na=x+1\n'
            base='a'
            if case=='nested':model+='v=slice(a,1,0,8)\n';base='v'
            first,last=(1,3) if case=='partial' else (4,8) if case=='reversed' else (0,3) if case=='gap' else (0,4)
            right,end=(3,5) if case=='partial' else (0,4) if case=='reversed' else (4,8)
            model+=f'l=slice({base},1,{first},{last})\nr=slice({base},1,{right},{end})\nc=concat(l,r,1)\nq=x*2\nd=concat(c,q,1)\noutput d,a\n'
            if case=='shared': model=f'x=input("observation",[{batch},8,2,3])\na=x+1\nb=x*2\nc=concat(a,b,1)\nd=a+b\ne=concat(c,d,1)\noutput e,a,b\n'
            if case=='duplicate': model=f'x=input("observation",[{batch},8,2,3])\na=x+1\nc=concat(a,a,1)\nb=x*2\nd=concat(c,b,1)\noutput d,a\n'
            if case=='multiple': model=f'x=input("observation",[{batch},8,2,3])\na=x+1\nb=x*2\nc=x-3\nl=concat(a,b,1)\nr=concat(a,c,1)\nz=concat(l,r,1)\noutput z,l,r,a\n'
            (directory/'model.pup').write_text(model);factory=directory/'factory.flex'
            subprocess.run([str(ROOT/'build/flex/compile-pup'),str(directory/'model.pup'),str(factory)],check=True)
            checkpoint(directory,[]);sha=json.loads((directory/'model.json').read_text())['weightsSha256']
            host=directory/'host.flex';binary=directory/'host'
            host.write_text(f'''import "{ROOT}/flex/ml/runtime.flex";
import "{factory}";
fn main(argc,argv) {{pl_init();if argc==2 {{vp_init(".",0,0);vp_compile_only=1;pup_build_model();let data=vp_plan_inventory();return pl_atomic_file(load64(argv+8),data,load64(vp_nodes)*224);}}
vp_init(load64(argv+16),vp_backend_parse(load64(argv+8)),0);vp_checkpoint_open("{directory}/weights.bin","{sha}");pup_build_model();let data=alloc(4096);let output=alloc(8192);let frame=0;let bytes=0;while frame<2 {{let i=0;while i<load64(vp_input+8) {{pb_put32(data+i*4,gpu_f32_from_i64(i-12+frame*37));i=i+1;}}vp_upload(load64(vp_input),data,load64(vp_input+8)*4);vp_execute();i=0;while i<load64(vp_outputs) {{let t=vp_at(vp_outputs,i);vp_read_tensor(t,output+bytes);bytes=bytes+load64(t+8)*4;i=i+1;}}frame=frame+1;}}return pl_atomic_file(load64(argv+24),output,bytes);}}
''')
            subprocess.run([compiler,str(host),'-o',str(binary)],check=True)
            inventory=directory/'graph.bin';subprocess.run([str(binary),str(inventory)],check=True)
            output=directory/'output.bin';reference=None;saved={}
            for enabled in (False,True):
                kernels=directory/str(enabled);kernels.mkdir()
                for path in (ROOT/'build/flex/pup-kernels').iterdir():
                    if path.suffix in ('.ptx','.cubin','.hip') or path.name=='kernels.json':shutil.copyfile(path,kernels/path.name)
                compile_plan(inventory.read_bytes(),kernels,compiler,['sass','cuda','hip'],join_views=enabled,shared_placement=enabled)
                metadata=json.loads((kernels/'plan.json').read_text())
                assert metadata['joinedViews']==int(enabled and case in ('adjacent','nested'));checks+=1
                for backend in ['cpu',*backends]:
                    subprocess.run([str(binary),backend,str(kernels),str(output)],check=True,timeout=30)
                    data=output.read_bytes()
                    if reference is None:reference=data
                    assert data==reference,(case,backend,enabled,'join changed output')
                    if not enabled:saved[backend]=data
                    checks+=len(data)//4
            for backend in backends:
                selected=directory/('selected-'+backend)
                compact(inventory.read_bytes(),directory/'False',selected,backend)
                metadata=json.loads((selected/'plan.json').read_text())
                assert metadata['joinedViews']==int(case in ('adjacent','nested'));checks+=1
                subprocess.run([str(binary),backend,str(selected),str(output)],check=True,timeout=30)
                assert output.read_bytes()==saved[backend],(case,backend,'selected join changed output')
                checks+=len(saved[backend])//4
    print(f'Pup adjacent joins: {checks} output and placement checks passed')


if __name__=='__main__':
    main()
