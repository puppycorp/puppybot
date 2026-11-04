"""Native tensor lowering must preserve strict-FP32 source, plans and options."""
import contextlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from flex.tests import reference_codegen as reference


def main():
    binary=ROOT/'build/flex/pup-codegen'
    inventory=ROOT/'build/flex/pup-graph.bin'
    variants=[('default',[],{}),('residual',['--residual-fusion'],{'residual_fusion':True}),
              ('scalar',['--no-vector','--staging','0','--no-pipeline'],{'vector':False,'staging':0,'pipeline':False}),
              ('unroll',['--unroll','3'],{'unroll':3}),
              ('patch',['--patch-tiles','--packed-masks'],{'patch_tiles':True,'packed_masks':True}),
              ('matrix',['--convolution','im2col'],{'convolution':'im2col'}),
              ('stencil',['--interior-stencil'],{'interior_stencil':True}),
              ('tensorcore',['--math','fp32-tc'],{'math_mode':'fp32-tc'}),
              ('nostream',['--no-streaming','--staging','2'],{'streaming':False,'staging':2}),
              ('nobatch',['--no-batch-epilogue'],{'batch_epilogue':False}),
              ('legacyplace',['--no-join-views','--no-shared-placement'],{'join_views':False,'shared_placement':False}),
              ('tile',['--tile','32,128,18,4,8','--staging','8'],{'tile':(32,128,18,4,8),'staging':8})]
    checks=0
    with tempfile.TemporaryDirectory(prefix='pup-native-codegen-') as temporary:
        base=Path(temporary)
        for name,args,options in variants:
            expected=base/(name+'-reference');actual=base/(name+'-native')
            with patch.object(reference.subprocess,'run'),contextlib.redirect_stdout(io.StringIO()):
                reference.compile_plan(inventory.read_bytes(),expected,'unused',[],**options)
            subprocess.run([str(binary),str(inventory),'--root',str(ROOT),'--emit-only','--output',str(actual),*args],check=True,stdout=subprocess.DEVNULL)
            a=json.loads((expected/'plan.json').read_text());b=json.loads((actual/'plan.json').read_text())
            assert a==b,(name,'metadata');checks+=1
            filename='plan-'+a['fingerprint']+'.bin'
            assert (expected/filename).read_bytes()==(actual/filename).read_bytes(),(name,'plan');checks+=1
            for source in expected.glob('*.flex'):
                assert source.read_bytes()==(actual/source.name).read_bytes(),(name,source.name);checks+=1
        # Input and CLI failures must be explicit, before compiling any kernels.
        bad=[b'',b'bad inventory']
        data=bytearray(inventory.read_bytes());struct.pack_into('<q',data,64,0);bad.append(bytes(data))
        for i,data in enumerate(bad):
            path=base/f'bad-{i}.bin';path.write_bytes(data)
            result=subprocess.run([str(binary),str(path),'--emit-only','--output',str(base/f'bad-{i}')],capture_output=True)
            assert result.returncode and b'Flexscript tool:' in result.stderr;checks+=1
        for args in (['--tile','0,16,32,4,4'],['--tile','32,64,32,4'],['--staging','3'],['--unroll','-1'],['--math','invalid'],['--unknown','x']):
            result=subprocess.run([str(binary),str(inventory),'--emit-only',*args],capture_output=True)
            assert result.returncode and b'Flexscript tool:' in result.stderr;checks+=1
    print(f'Native Pup codegen: {checks} source, binary-plan, metadata and rejection checks passed')


if __name__=='__main__':
    main()
