"""Backend plans retain the common fallback and expire when their graph is rebuilt."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'flex/ml'))
from codegen import compile_plan
from install import install


def main():
    checks=0
    with tempfile.TemporaryDirectory(prefix='puppybot-install-') as temporary:
        directory=Path(temporary);source=directory/'source';source.mkdir();output=directory/'kernels';output.mkdir()
        row=[0]*28;row[0]=3;row[8:20]=[1]*12;row[24:28]=[-1,-1,0,1]
        inventory=struct.pack('<28q',*row);fingerprint=hashlib.sha256(inventory).hexdigest()
        raw=struct.pack('<8sQ64s64s8Q',b'PPLN0001',1,fingerprint.encode(),b'kernel',0,128,1,0,0,0,0,0)
        name=f'plan-{fingerprint}.bin';(source/name).write_bytes(raw);(output/name).write_bytes(raw)
        metadata=dict(fingerprint=fingerprint,mathMode='fp32',nodes=1,schedule=[dict(index=0,kernel='kernel')])
        (source/'plan.json').write_text(json.dumps(metadata));(source/'kernel.flex').write_text('fn main() {return 0;}\n')
        (source/'kernel.cubin').write_bytes(b'native image');(source/'kernel.ptx').write_bytes(b'ptx image')
        (output/'generic.ptx').write_bytes(b'common fallback kernel')
        for backend in ('sass','cuda'):
            report=install(source,output,backend)
            path=output/f'plan-{backend}-{fingerprint}.bin';actual=path.read_bytes()
            assert actual[:80]==raw[:80] and actual[144:]==raw[144:];checks+=1
            assert hashlib.sha256(actual).hexdigest()==report['installedPlanSha256'];checks+=1
            assert (output/name).read_bytes()==raw;checks+=1
            for leaf,sha in report['artifacts'].items():
                assert hashlib.sha256((output/leaf).read_bytes()).hexdigest()==sha;checks+=1
            install(source,output,backend);assert path.read_bytes()==actual;checks+=1
        assert (output/'generic.ptx').read_bytes()==b'common fallback kernel';checks+=1
        compile_plan(inventory,output,'/bin/false',[])
        for backend in ('sass','cuda'):
            for suffix in ('.bin','.json'):
                assert not (output/f'plan-{backend}-{fingerprint}{suffix}').exists();checks+=1
        assert (output/name).exists() and (output/'generic.ptx').exists();checks+=1
        metadata['mathMode']='fp32-tc';(source/'plan.json').write_text(json.dumps(metadata))
        try:install(source,output,'sass')
        except ValueError as error:assert 'FP32' in str(error)
        else:raise AssertionError('approximate plan installed as FP32')
        checks+=1
    print(f'Pup installation: {checks} fallback, artifact and rebuild checks passed')


if __name__=='__main__':
    main()
