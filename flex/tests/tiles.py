"""Exact independent convolution checks for non-power-of-two reduction tiles."""
import json
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
from flex.tests.vision import checkpoint


def main():
    compiler=os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler'))
    backends=os.environ.get('PUPPYBOT_TEST_BACKENDS','').split()
    checks=0
    cases=[(2,6,7,9,16,3,1,1,2,None),
           (1,18,3,5,8,1,1,0,1,(8,16,9,1,2)),
           (1,4,10,10,32,3,2,1,1,None),
           (1,18,5,26,32,1,1,0,1,(32,128,9,4,8)),
           (1,4,8,8,32,3,1,1,1,(32,128,18,4,8))]
    with tempfile.TemporaryDirectory(prefix='puppybot-tiles-') as temporary:
        for case,(batch,cin,ih,iw,cout,k,stride,pad,groups,tile) in enumerate(cases):
            directory=Path(temporary)/str(case);directory.mkdir()
            source=directory/'model.pup';factory=directory/'factory.flex'
            source.write_text(f'x=input("observation",[{batch},{cin},{ih},{iw}])\nc=conv2d(x,"filter",{cout},{k},{stride},{pad},1,{groups})\noutput c\n')
            subprocess.run([str(ROOT/'build/flex/compile-pup'),str(source),str(factory)],check=True)
            x=[(i*7%31-15)/32 for i in range(batch*cin*ih*iw)]
            w=[(i*3%17-8)/64 for i in range(cout*(cin//groups)*k*k)]
            bias=[(i%7-3)/16 for i in range(cout)]
            checkpoint(directory,[('filter.weight',[cout,cin//groups,k,k],w),('filter.bias',[cout],bias)])
            sha=json.loads((directory/'model.json').read_text())['weightsSha256']
            (directory/'input.bin').write_bytes(struct.pack('<'+'f'*len(x),*x))
            host=directory/'host.flex';binary=directory/'host'
            host.write_text(f'''import "{ROOT}/flex/ml/runtime.flex";
import "{factory}";
fn main(argc,argv) {{pl_init();if argc==2 {{vp_init(".",0,0);vp_compile_only=1;pup_build_model();let data=vp_plan_inventory();return pl_atomic_file(load64(argv+8),data,load64(vp_nodes)*224);}}
vp_init(load64(argv+16),vp_backend_parse(load64(argv+8)),0);vp_checkpoint_open("{directory}/weights.bin","{sha}");pup_build_model();let bytes=load64(vp_input+8)*4;let data=alloc(pb_max(bytes,load64(vp_output+8)*4)+1);vp_require(pl_read_file("{directory}/input.bin",data,bytes+1)==bytes,"input length");vp_upload(load64(vp_input),data,bytes);vp_execute();vp_read_output(data);return pl_atomic_file(load64(argv+24),data,load64(vp_output+8)*4);}}
''')
            subprocess.run([compiler,str(host),'-o',str(binary)],check=True)
            inventory=directory/'graph.bin';subprocess.run([str(binary),str(inventory)],check=True)
            oh=(ih+2*pad-k)//stride+1;ow=(iw+2*pad-k)//stride+1
            expected=[]
            for n in range(batch):
                for c in range(cout):
                    for y in range(oh):
                        for xx in range(ow):
                            total=bias[c]
                            for ci in range(cin//groups):
                                channel=c//(cout//groups)*(cin//groups)+ci
                                for ky in range(k):
                                    for kx in range(k):
                                        iy=y*stride+ky-pad;ix=xx*stride+kx-pad
                                        if 0<=iy<ih and 0<=ix<iw:
                                            total+=x[((n*cin+channel)*ih+iy)*iw+ix]*w[((c*(cin//groups)+ci)*k+ky)*k+kx]
                            expected.append(total)
            expected_bytes=struct.pack('<'+'f'*len(expected),*expected)
            output=directory/'output.bin'
            for label,options in [('full',{}),('compact',dict(unroll=3,packed_masks=True))]:
                kernels=directory/label;kernels.mkdir()
                for path in (ROOT/'build/flex/pup-kernels').iterdir():
                    if path.suffix in ('.ptx','.cubin','.hip'):shutil.copyfile(path,kernels/path.name)
                compile_plan(inventory.read_bytes(),kernels,compiler,['sass','cuda','hip'],tile=tile,patch_tiles=True,**options)
                for backend in ['cpu',*backends]:
                    subprocess.run([str(binary),backend,str(kernels),str(output)],check=True,timeout=30)
                    assert output.read_bytes()==expected_bytes,(case,backend,tile,label)
                    checks+=len(expected)
    print(f'Pup convolution tiles: {checks} exact independent output checks passed')


if __name__=='__main__':
    main()
