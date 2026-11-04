# Non-GPU end-to-end client test using stub simulator and stub policy processes.
# Usage: python3 -I flex/tests/physical-client-stub.py COMPILED_CLIENT
import os,sys,tempfile,subprocess,json,hashlib
from pathlib import Path
if len(sys.argv) != 2:
 raise SystemExit('usage: physical-client-stub.py COMPILED_CLIENT')
client = str(Path(sys.argv[1]).resolve())
project = str(Path(__file__).resolve().parents[2])
with tempfile.TemporaryDirectory(prefix='puppy-client-') as d:
 root=Path(d); m=root/'model'; m.mkdir(); (m/'kernels').mkdir(); (m/'weights.bin').write_bytes(b'weights')
 policy='''#!/usr/bin/env python3\nimport socket,struct,os\ns=socket.socket(fileno=3);s.sendall(b"VCPOL001")\ndef read(n):\n b=b""\n while len(b)<n:\n  x=s.recv(n-len(b))\n  if not x: raise EOFError()\n  b+=x\n return b\ntry:\n while True:\n  v=read((21168+7+128)*4);open(os.environ["PUPPY_STUB_CAPTURE"],"ab").write(v);s.sendall(struct.pack("<130f",0.0,0.2,*([0.0]*128)))\nexcept EOFError:pass\n'''
 (m/'policy').write_text(policy); (m/'policy').chmod(0o755)
 kernels={}
 for i in range(5):
  n=f'kernel{i}';data=f'kernel{i}'.encode();(m/'kernels'/n).write_bytes(data);kernels[n]=hashlib.sha256(data).hexdigest()
 sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
 (m/'receipt.json').write_text(json.dumps({'weightsSHA256':sha(m/'weights.bin'),'binarySHA256':sha(m/'policy'),'memoryWidth':128,'kernels':kernels}))
 sim=root/'simulator';sim.write_text('''#!/usr/bin/env python3\nimport socket,struct,json,sys,os\ns=socket.socket(fileno=3);step=100;detect=int(os.environ.get("PUPPY_STUB_VISIBLE", "0"));mutation=os.environ.get("PUPPY_STUB_MUTATION", "")\nif mutation != "no_trace": open(sys.argv[sys.argv.index("--record")+1], "w").write("stub-trace\\n")\ndef read(n):\n b=b""\n while len(b)<n:\n  x=s.recv(n-len(b))\n  if not x: raise EOFError()\n  b+=x\n return b\ntry:\n while True:\n  command,seq,steer,speed,hold,_,task,_=struct.unpack("<8q",read(64));owner=0;valid=True;ack=0;drive=[0,0,90]\n  if command==2: step+=hold;detect=1;ack=1;drive=[int(speed*60/1000)]*2+[90+int(int(steer/10)*45/100)]\n  elif command==6:step+=2;owner=1;valid=False;ack=3\n  elif command==7:step+=hold;owner=2;valid=False;ack=5\n  elif command==3:owner=2;valid=False;ack=7\n  if command==2 and mutation=="drive":drive[0]=99\n  if command==2 and mutation=="stale":step-=1\n  x={"schema":"puppybot.physical-agent.v1","sequence":seq,"step":step,"timeMs":step*20,"owner":owner,"ack":ack,"imageValid":valid,"rgbDetections":detect if valid else None,"totalSteps":step,"cameraFrame":step if valid else -1,"cameraDriving":valid,"cameraStill":valid,"driveCommand":drive,"jointTicks":[1,2,3,4]}\n  js=(json.dumps(x)+"\\n").encode();s.sendall(struct.pack("<4q",len(js),640*480*3,seq,0)+js+(bytes([128,64,255])*(640*480) if valid else bytes(640*480*3)))\n  if command==3:break\nexcept EOFError:pass\n'''); sim.chmod(0o755)
 case=root/'case.json';case.write_text('{}');environment=root/'environment.bin';environment.write_bytes(b'fake')
 for scenario,visible,mutation in [('normal',0,''),('visible',1,''),('wrong_drive',0,'drive'),('stale',0,'stale'),('missing_trace',0,'no_trace')]:
  out=root/scenario; env={**os.environ,'PUPPY_STUB_VISIBLE':str(visible),'PUPPY_STUB_MUTATION':mutation,'PUPPY_STUB_CAPTURE':str(root/(scenario+'.input'))}
  r=subprocess.run([client,str(sim),str(m),str(case),str(environment),str(out),'--allow-zero-contact'],capture_output=True,text=True,timeout=40,cwd=project,env=env)
  if not mutation:
   assert r.returncode==0,(scenario,r.stderr, (out/'native.log').read_text() if (out/'native.log').exists() else '', (out/'policy.log').read_text() if (out/'policy.log').exists() else '');result=json.loads((out/'result.json').read_text());assert result['policyActions']==1-visible and result['handoff'] and result['collectorTerminal'] and result['stopCommandAcknowledged'] and result['outcome']=='unverified' and result['traceSHA256']==sha(out/'trace.jsonl'),result
   files=sorted(x.name for x in (out/'actors').iterdir());assert len(files)==4*(1-visible),files
   if not visible:
    import struct
    rgb=(out/'actors/actor-1.rgb').read_bytes(); assert rgb==bytes([128])*7056+bytes([64])*7056+bytes([255])*7056
    expected=b''.join(struct.pack('<f',v/255)*7056 for v in (128,64,255))+bytes(28+512);assert (root/(scenario+'.input')).read_bytes()==expected
    assert (out/'actors/actor-1.feedback').read_bytes()==bytes(28)
    assert (out/'actors/actor-1.hidden').read_bytes()==bytes(512)
    a=struct.unpack('<2f',(out/'actors/actor-1.action').read_bytes());assert abs(a[1]-.2)<1e-6,a
   print(scenario,'passed:',result)
  else:
   assert r.returncode!=0 and not (out/'result.json').exists(),(scenario,r.stdout,r.stderr)
   print(scenario,'rejected:',r.stderr.strip())
