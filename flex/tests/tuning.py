"""Kernel preparation identity and stale-profile regression checks; no GPU needed."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'flex/ml'))
from codegen import compile_plan
from tune import candidate, select


def main():
    compiler=os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler'))
    checks=0
    with tempfile.TemporaryDirectory(prefix='puppybot-tuning-') as directory:
        directory=Path(directory);kernels=directory/'kernels'
        rows=[]
        # Both convolutions produce the same matrix dimensions. One crops a
        # 10x10 image; the other pads an 8x8 image. Their preparations differ.
        for size,pad in ((10,0),(8,1)):
            row=[0]*28;row[0]=12;row[8:12]=[1,32,8,8];row[12:16]=[1,8,size,size]
            row[20:24]=[3,1,pad,1];row[24:28]=[-1,-1,1,1];rows.append(struct.pack('<28q',*row))
        compile_plan(b''.join(rows),kernels,compiler,['cuda'],convolution='im2col')
        metadata=json.loads((kernels/'plan.json').read_text());schedule=metadata['schedule']
        first,second=(row['kernel'] for row in schedule)
        assert first!=second;checks+=1
        assert (kernels/(first+'.ptx')).read_bytes()==(kernels/(second+'.ptx')).read_bytes();checks+=1
        assert (kernels/(first+'-input.ptx')).read_bytes()!=(kernels/(second+'-input.ptx')).read_bytes();checks+=1
        (kernels/'kernels.json').write_text('{}\n')
        data=(kernels/f"plan-{metadata['fingerprint']}.bin").read_bytes()
        records=[]
        for row in schedule:
            name=row['kernel']
            records.append(dict(index=row['index'],ms=1,backend='cuda',
                                planSha256=hashlib.sha256(data).hexdigest(),
                                kernelSha256=hashlib.sha256((kernels/(name+'.ptx')).read_bytes()).hexdigest(),
                                prepareSha256=hashlib.sha256((kernels/(name+'-input.ptx')).read_bytes()).hexdigest()))
        profile=directory/'profile.jsonl'
        profile.write_text(''.join(json.dumps(row)+'\n' for row in records))
        baseline=candidate(kernels,profile,'cuda');assert len(baseline['times'])==2;checks+=1
        selected=directory/'selected';select([baseline],selected,'cuda',.05)
        chosen=json.loads((selected/'selection.json').read_text())
        assert chosen[0]['kernel']!=chosen[1]['kernel'];checks+=1
        for original,row in zip(schedule,chosen):
            for suffix in ('.ptx','-input.ptx'):
                assert (selected/(row['kernel']+suffix)).read_bytes()==(kernels/(original['kernel']+suffix)).read_bytes();checks+=1
        bad=directory/'bad.jsonl'
        invalid=[([records[0],records[0]],'duplicate'),
                 ([dict(records[0],mode='graph'),dict(records[1],mode='hot')],'methods'),
                 ([dict(records[0],mode='unknown')],'methods'),
                 ([dict(records[0],backend='sass')],'backend'),
                 ([dict(records[0],planSha256='0'*64)],'plan'),
                 ([dict(records[0],kernelSha256='0'*64)],'kernel'),
                 ([dict(records[0],prepareSha256='0'*64)],'preparation'),
                 ([dict(index=0,ms=1)],'not bound')]
        invalid += [([dict(records[0],ms=value)],'timing') for value in (0,-1,float('inf'),float('nan'))]
        for values,message in invalid:
            bad.write_text(''.join(json.dumps(row)+'\n' for row in values))
            try: candidate(kernels,bad,'cuda')
            except ValueError as error: assert message in str(error)
            else: raise AssertionError('invalid timing profile accepted')
            checks+=1
        profile.write_text(''.join(json.dumps(dict(row,mode='graph'))+'\n' for row in records))
        graph=candidate(kernels,profile,'cuda')
        try: select([baseline,graph],directory/'mixed','cuda',.05)
        except ValueError as error: assert 'profiling methods differ' in str(error)
        else: raise AssertionError('mixed hot and graph timings accepted')
        checks+=1
        native=kernels/(first+'.ptx');saved=native.read_bytes();native.write_bytes(saved+b'\n// rebuilt\n')
        try: candidate(kernels,profile,'cuda')
        except ValueError as error: assert 'kernel differs' in str(error)
        else: raise AssertionError('rebuilt kernel accepted old timing')
        checks+=1
    print(f'Pup tuning: {checks} preparation identity and profile checks passed')


if __name__=='__main__':
    main()
