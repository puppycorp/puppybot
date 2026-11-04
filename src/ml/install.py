"""Install a measured FP32 plan for one backend while retaining the common plan."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from codegen import TARGETS
from fuse import leaf


def immutable(path, data):
    if path.exists():
        if path.read_bytes()!=data:raise ValueError('installed artifact conflicts with its content hash')
        return
    temporary=path.with_name(path.name+'.tmp');temporary.write_bytes(data);temporary.replace(path)


def install(directory, output, backend):
    directory=Path(directory).resolve();output=Path(output).resolve()
    if directory==output:raise ValueError('choose a separate kernel directory')
    metadata=json.loads((directory/'plan.json').read_text())
    if metadata['mathMode']!='fp32':raise ValueError('installation requires an FP32 plan')
    if metadata.get('backend',backend)!=backend:raise ValueError('selected plan backend differs')
    fingerprint=metadata['fingerprint'];count=metadata['nodes']
    if len(fingerprint)!=64 or any(c not in '0123456789abcdef' for c in fingerprint):raise ValueError('invalid graph fingerprint')
    raw=(directory/f'plan-{fingerprint}.bin').read_bytes();header=struct.pack('<8sQ64s',b'PPLN0001',count,fingerprint.encode())
    if len(raw)!=80+count*128 or raw[:80]!=header:raise ValueError('invalid candidate plan')
    common=(output/f'plan-{fingerprint}.bin').read_bytes()
    if len(common)!=len(raw) or common[:80]!=header:raise ValueError('kernel directory graph differs')
    suffix='.'+TARGETS[backend][1];data=bytearray(raw);artifacts={}
    for i in range(count):
        at=80+i*128
        if struct.unpack_from('<Q',data,at+96)[0]:continue
        name=leaf(data[at:at+64].split(b'\0',1)[0].decode());native=(directory/(name+suffix)).read_bytes()
        flags=struct.unpack_from('<Q',data,at+104)[0]
        if flags&7 not in (0,4):raise ValueError('candidate numerical flags differ from FP32')
        prepare=(directory/(name+'-input'+suffix)).read_bytes() if flags&4 else b''
        identity=struct.pack('<Q',len(native))+native+prepare;renamed='i'+hashlib.sha256(identity).hexdigest()[:24]
        for tail,image in ((suffix,native),('-input'+suffix,prepare)):
            if not image:continue
            path=output/(renamed+tail);immutable(path,image);artifacts[path.name]=hashlib.sha256(image).hexdigest()
        for tail in ('.flex','-input.flex'):
            source=directory/(name+tail);destination=output/(renamed+tail)
            if source.exists() and not destination.exists():destination.write_bytes(source.read_bytes())
        data[at:at+64]=struct.pack('<64s',renamed.encode())
    path=output/f'plan-{backend}-{fingerprint}.bin'
    receipt=dict(backend=backend,mathMode='fp32',fingerprint=fingerprint,source=str(directory),
                 sourcePlanSha256=hashlib.sha256(raw).hexdigest(),installedPlanSha256=hashlib.sha256(data).hexdigest(),artifacts=artifacts)
    temporary=path.with_suffix('.json.tmp');temporary.write_text(json.dumps(receipt,indent=2)+'\n');temporary.replace(path.with_suffix('.json'))
    temporary=path.with_suffix('.bin.tmp');temporary.write_bytes(data);temporary.replace(path)
    print(json.dumps(dict(backend=backend,plan=str(path),artifacts=len(artifacts))),flush=True)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--backend',choices=TARGETS,required=True)
    args=parser.parse_args();install(args.candidate,args.output,args.backend)


if __name__=='__main__':
    main()
