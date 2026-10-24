"""Whole-model search rejects fast wrong outputs, child failures and duplicate code."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'flex/ml'))
from search import search
from tune import candidate


def main():
    with tempfile.TemporaryDirectory(prefix='puppybot-search-') as temporary:
        directory=Path(temporary);fingerprint='a'*64;plans=[]
        for label,code,timing in [('baseline',b'baseline',1),('duplicate',b'baseline',.01),('failed',b'failure',.05),('wrong',b'wrong',.1),('valid',b'fast',.5)]:
            path=directory/label;path.mkdir();image=path/'kernel.ptx';image.write_bytes(code)
            raw=struct.pack('<8sQ64s64s8Q',b'PPLN0001',1,fingerprint.encode(),b'kernel',0,128,1,0,0,0,0,0)
            (path/f'plan-{fingerprint}.bin').write_bytes(raw)
            metadata=dict(fingerprint=fingerprint,mathMode='fp32',nodes=1,schedule=[dict(index=0,kernel='kernel')])
            (path/'plan.json').write_text(json.dumps(metadata));(path/'kernels.json').write_text('{}')
            profile=path/'profile.jsonl';profile.write_text(json.dumps(dict(index=0,ms=timing,mode='graph',backend='cuda',planSha256=hashlib.sha256(raw).hexdigest(),kernelSha256=hashlib.sha256(code).hexdigest(),prepareSha256=''))+'\n')
            plans.append(candidate(path,profile,'cuda'))
        binary=directory/'benchmark'
        binary.write_text(f'''#!{sys.executable}
import json,pathlib,struct,sys
directory=pathlib.Path(sys.argv[2]);metadata=json.loads((directory/'plan.json').read_text());raw=(directory/('plan-'+metadata['fingerprint']+'.bin')).read_bytes();name=raw[80:144].split(b'\\0',1)[0].decode();code=(directory/(name+'.ptx')).read_bytes()
if code==b'failure':print('deliberate benchmark failure',file=sys.stderr);sys.exit(1)
pathlib.Path(sys.argv[5]).write_bytes(struct.pack('<f',2 if code==b'wrong' else 1))
print(json.dumps([1000000 if code==b'wrong' else 3000000 if code==b'fast' else 4000000]*30))
''');binary.chmod(0o755)
        weights=directory/'weights.bin';weights.write_bytes(b'weights');input_path=directory/'input.bin';input_path.write_bytes(struct.pack('<f',1))
        report=search(plans,directory/'result','cuda',binary,weights,hashlib.sha256(weights.read_bytes()).hexdigest(),[input_path],trials=4,alternatives=4)
        assert len(report['trials'])==3,'identical code should not be benchmarked'
        failures={Path(row['candidate']).name:row for row in report['trials']}
        assert 'benchmark failed' in failures['failed']['rejection']
        assert 'output differs' in failures['wrong']['rejection']
        assert failures['valid']['accepted']
        assert report['selected']=={'0':str(directory/'valid')}
        assert report['baseline']['medianNs']==4000000 and report['final']['medianNs']==3000000
        assert report['baseline']['outputSha256']==report['final']['outputSha256']
        assert not failures['wrong']['accepted'] and not failures['failed']['accepted']
        print('Pup whole-model search: 8 output, rollback, identity and confirmation checks passed')


if __name__=='__main__':
    main()
