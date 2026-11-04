#!/usr/bin/env python3
"""CPU-only one-action virtual-chase parity with fake simulator/policy peers.

Both disposable binaries relax only the kick experiment's 300-action guard to
one action. This is not proof of full-horizon or rendered simulator parity.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SAVED=ROOT/'build/flex/sim/levels-v2/pitch82/search-dagger-l35-4workers/selection-L5/student-s2/0/7800001'
LAYOUT=ROOT/'build/flex/sim/expanded-rooms-v1/scenes/15/1/layout.json'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


class DispatchParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        if not (SAVED/'initial.json').is_file() or not LAYOUT.is_file():raise FileNotFoundError('saved CPU fixture unavailable')
        cls.binaries=[]
        for name,path in [('old',ROOT/'experiments/l5-steering-kick-v1/transform.py'),('new',HERE/'transform.py')]:
            source=cls.root/name/'flex';source.parent.mkdir();shutil.copytree(ROOT/'flex',source,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            transform=load(name,path);chase=source/'control/chase.flex';main=source/'control/main.flex'
            c,m=transform.transform(chase.read_text(),main.read_text());guard='vw_horizon==300'
            if m.count(guard)!=1:raise ValueError('expected one fixed-horizon guard')
            chase.write_text(c);main.write_text(m.replace(guard,'vw_horizon==1'))
            binary=cls.root/name/'control';subprocess.run([str(ROOT/'build/flex/control/compiler'),str(main),'-o',str(binary)],check=True,cwd=ROOT,capture_output=True,timeout=120)
            cls.binaries.append(binary)
        (cls.root/'initial.json').write_bytes((SAVED/'initial.json').read_bytes())
        with (SAVED/'decisions.jsonl').open() as stream:first=json.loads(stream.readline())
        (cls.root/'first.json').write_text(json.dumps(first))
        simulator=cls.root/'build/flex/control/simulator';simulator.parent.mkdir(parents=True)
        simulator.write_text('''#!/usr/bin/python3
import json,os,struct
from pathlib import Path
r=Path(os.environ['STUB_ROOT']);(r/'sim-start').write_text('started');a=json.loads((r/'initial.json').read_text());b=json.loads((r/'first.json').read_text())['state']
def read(n):
 d=b''
 while len(d)<n:
  x=os.read(3,n-len(d))
  if not x:raise EOFError()
  d+=x
 return d
try:
 while True:
  command,sequence,steering,speed,*_=struct.unpack('<8q',read(64))
  with (r/'sim-commands').open('a') as f:f.write(str(command)+'\\n')
  if command==3:break
  state=b if command==2 else a
  if command==2:
   throttle=int(speed*60/1000) if abs(speed)>=80 else 0
   drive=state['controller']['drive'];drive['leftSpeed']=throttle;drive['rightSpeed']=throttle;drive['steeringAngleDeg']=90+int(int(steering/10)*45/100)
  data=(json.dumps(state,separators=(',',':'))+'\\n').encode();wire=struct.pack('<4q',len(data),921600,sequence,0)+data+bytes(921600)
  while wire:wire=wire[os.write(3,wire):]
except EOFError:(r/'sim-eof').write_text('peer closed')
''');simulator.chmod(0o755)
        model=cls.root/'model';(model/'kernels').mkdir(parents=True);(model/'weights.bin').write_bytes(b'weights')
        policy=model/'policy';policy.write_text('''#!/usr/bin/python3
import json,os,struct
from pathlib import Path
r=Path(os.environ['STUB_ROOT']);out=Path(os.environ['STUB_CAPTURE']);os.write(3,b'VCPOL001')
def read(n):
 d=b''
 while len(d)<n:
  x=os.read(3,n-len(d))
  if not x:raise EOFError()
  d+=x
 return d
try:
 data=read((21168+7+128)*4);(out/'peer-input.bin').write_bytes(data)
 action=json.loads((r/'first.json').read_text())['action'];response=struct.pack('<130f',*action,*([0.0]*128));(out/'peer-output.bin').write_bytes(response);os.write(3,response)
 while os.read(3,1):pass
except EOFError:(out/'policy-eof').write_text('peer closed')
''');policy.chmod(0o755)
        kernels={}
        for i in range(5):
            p=model/'kernels'/f'{i}.hip';p.write_bytes(f'kernel {i}'.encode());kernels[p.name]=digest(p)
        (model/'receipt.json').write_text(json.dumps({'weightsSHA256':digest(model/'weights.bin'),'binarySHA256':digest(policy),'kernels':kernels}))
        scene=cls.root/'catalog/0';scene.mkdir(parents=True)
        for name in ('case.json','environment.bin'):shutil.copyfile(SAVED/'scene'/name,scene/name)
        shutil.copyfile(LAYOUT,scene/'layout.json')

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_one_action_old_and_new_hysteresis_disabled(self):
        for flag in (None,'--steer-probe-control','--steer-probe-enabled'):
            outputs=[]
            for index,binary in enumerate(self.binaries):
                capture=self.root/('capture-'+str(flag)+'-'+str(index));capture.mkdir();output=self.root/('out-'+str(flag)+'-'+str(index))
                env=os.environ.copy();env.update(STUB_ROOT=str(self.root),STUB_CAPTURE=str(capture))
                command=[str(binary),'run','--chase','--fetch','--policy',str(self.root/'model'),'--scene-catalog',str(self.root/'catalog'),'--output',str(output),'--episodes','1','--horizon','1','--seed','7800001','--level','5','--lean','--wheel-odometry','--camera-pitch','82']
                if flag:command.append(flag)
                done=subprocess.run(command,cwd=self.root,env=env,capture_output=True,text=True,timeout=20)
                logs='\n'.join(str(p)+': '+p.read_text(errors='replace') for p in output.rglob('*.log'))+'\n'+' '.join(str(p.name) for p in capture.iterdir())+'\n'+('commands='+ (self.root/'sim-commands').read_text() if (self.root/'sim-commands').exists() else 'sim-start='+str((self.root/'sim-start').exists()))
                self.assertEqual(done.returncode,0,done.stderr+'\n'+logs)
                game=output/'7800001';outputs.append(((capture/'peer-input.bin').read_bytes(),(capture/'peer-output.bin').read_bytes(),(game/'decisions.jsonl').read_bytes(),(game/'result.json').read_bytes(),(game/'steer-probe.jsonl').read_bytes() if flag else None))
                self.assertFalse((game/'hysteresis.jsonl').exists())
            self.assertEqual(outputs[0],outputs[1],flag)


if __name__=='__main__':unittest.main()
