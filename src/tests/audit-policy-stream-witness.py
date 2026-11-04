#!/usr/bin/env python3
"""Join a complete policy-stream witness to an actor-buffer journal.

This compares recorded transport hashes against each recorded actor request/
response. The supplied supervisor status and registration are unverified
self-declarations: neither is bound to this stream or proven pre-run. It
cannot prove actual invocation, child reads, model execution or runtime identity.
"""
import base64
import binascii
import hashlib
import os
import json
import struct
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
INPUT=(21168+7+128)*4
OUTPUT=(2+128)*4


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def exact(stream,size):
    data=stream.read(size)
    if len(data)!=size:raise ValueError('truncated actor journal')
    return data


def verify_registration(registration,model):
    data=json.loads(registration.read_text());paths=data.get('paths');files=data.get('files');argv=data.get('intendedControlArgvBase64')
    if data.get('schema')!='puppybot.policy-witness-registration.v1' or not isinstance(paths,dict) or not isinstance(files,dict):
        raise ValueError('invalid witness registration')
    for key in ('control','simulator','case','environment','witness','supervisor','model'):
        if not isinstance(paths.get(key),str) or not Path(paths[key]).is_absolute():raise ValueError('missing registration path: '+key)
    if Path(paths['model'])!=model or Path(paths['witness'])!=ROOT/'flex/tests/policy-stream-witness.py':raise ValueError('registration model/witness path differs')
    kernels=model/'kernels';required=[Path(paths[key]) for key in ('control','simulator','case','environment','witness','supervisor')]
    required += [model/'policy',model/'weights.bin',model/'receipt.json',*sorted(kernels.iterdir())]
    if any(str(p) not in files for p in required):raise ValueError('required input is not pinned')
    for name,digest in files.items():
        if not isinstance(name,str) or not Path(name).is_absolute() or not isinstance(digest,str) or len(digest)!=64 or sha(Path(name))!=digest:
            raise ValueError('registered input changed')
    if not isinstance(argv,list) or not 1<=len(argv)<=128 or any(not isinstance(x,str) for x in argv):raise ValueError('invalid intended control argv')
    try:decoded=[base64.b64decode(x,validate=True) for x in argv]
    except (binascii.Error,ValueError) as error:raise ValueError('invalid intended argv encoding') from error
    if decoded[0]!=os.fsencode(paths['control']) or any(len(x)>131072 or b'\0' in x for x in decoded):raise ValueError('invalid intended argv bytes')
    return data


def audit(witness,actor,model,supervisor,registration):
    witness=Path(witness);actor=Path(actor);model=Path(model);supervisor=Path(supervisor);registration=Path(registration)
    verify_registration(registration,model)
    status=json.loads(supervisor.read_text())
    if type(status.get('clientExit')) is not int or status['clientExit']!=0 or status.get('timedOut') is not False or status.get('remainingWorkersTerminated') is not False or status.get('signal') is not None or type(status.get('processGroup')) is not int or status['processGroup']<=0:
        raise ValueError('witness supervisor did not finish cleanly')
    receipt=model/'receipt.json';policy=model/'policy';weights=model/'weights.bin';kernels=model/'kernels'
    declared=json.loads(receipt.read_text());kernel_files=sorted(kernels.iterdir())
    if len(kernel_files)<5 or any(not p.is_file() for p in kernel_files):raise ValueError('invalid kernel files')
    kernel_shas={p.name:sha(p) for p in kernel_files};policy_sha=sha(policy);weights_sha=sha(weights)
    if declared.get('binarySHA256')!=policy_sha or declared.get('weightsSHA256')!=weights_sha or declared.get('kernels')!=kernel_shas:
        raise ValueError('model receipt mismatch')
    with witness.open() as stream:events=[json.loads(line) for line in stream]
    if len(events)<3:raise ValueError('incomplete witness')
    head=events[0];footer=events[-1];rows=events[1:-1]
    if (head.get('schema')!='puppybot.policy-stream-witness.v1' or head.get('policySHA256')!=policy_sha
            or head.get('weightsSHA256')!=weights_sha or head.get('receiptSHA256')!=sha(receipt)
            or head.get('kernelSHA256')!=kernel_shas or head.get('witnessSHA256')!=sha(ROOT/'flex/tests/policy-stream-witness.py')
            or head.get('inputBytes')!=INPUT or head.get('outputBytes')!=OUTPUT):raise ValueError('witness input identity differs')
    if (footer!={'footer':'complete','frames':len(rows),'policyExit':0} or type(footer.get('frames')) is not int or type(footer.get('policyExit')) is not int or not 1<=len(rows)<=512
            or any(set(row)!={'sequence','inputSHA256','outputSHA256'} or type(row['sequence']) is not int or row['sequence']!=i for i,row in enumerate(rows))):
        raise ValueError('incomplete, unordered or malformed witness')
    with actor.open('rb') as stream:
        magic,version,seed,horizon,image_bytes,width,record_bytes=struct.unpack('<8s6q',exact(stream,56))
        if (magic!=b'PBATST01' or version!=1 or horizon!=len(rows) or image_bytes!=21168 or width!=128
                or record_bytes!=24+image_bytes+INPUT+OUTPUT+8):raise ValueError('actor dimensions or count differ')
        last_sequence=last_frame=-1
        for index,row in enumerate(rows):
            number,sequence,frame=struct.unpack('<3q',exact(stream,24));exact(stream,image_bytes)
            incoming=exact(stream,INPUT);outgoing=exact(stream,OUTPUT);action=exact(stream,8)
            if number!=index or sequence<=last_sequence or frame<=last_frame:raise ValueError('actor record ordering differs')
            if row['inputSHA256']!=hashlib.sha256(incoming).hexdigest() or row['outputSHA256']!=hashlib.sha256(outgoing).hexdigest():
                raise ValueError('witness/actor stream mismatch')
            if action!=outgoing[:8]:raise ValueError('actor action differs from response')
            last_sequence,last_frame=sequence,frame
        end,count=struct.unpack('<8sq',exact(stream,16))
        if end!=b'PBDONE01' or count!=horizon or stream.read(1):raise ValueError('invalid actor footer')
    return {'status':'stream_digests_consistent_unverified_provenance','frames':len(rows),'seed':seed,
            'supervisorStatus':'caller_supplied_unverified','registrationTiming':'unverified','actorJournalSHA256':sha(actor),
            'witnessJournalSHA256':sha(witness),'supervisorSHA256':sha(supervisor),'registrationSHA256':sha(registration),'modelReceiptSHA256':sha(receipt),
            'scope':'matching recorded actor and proxy-side socket hashes only; supplied supervisor status is not bound to this run, registration timing is unverified, and OS exec, child reads, GPU/runtime identity, model computation, camera authenticity and tampering are not established'}


if __name__=='__main__':
    if len(sys.argv)!=6:raise SystemExit(__doc__)
    try:print(json.dumps(audit(*sys.argv[1:]),sort_keys=True))
    except (OSError,ValueError,KeyError,TypeError,struct.error) as error:raise SystemExit(f'Invalid policy stream evidence: {error}')
