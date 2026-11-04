#!/usr/bin/env python3
"""CPU-only real-client / fake-peer tests for simulator visual stopping."""
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('builder', ROOT / 'flex/tests/prepare-sim-visual-stop.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class SimVisualStopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.root = Path(cls.tmp.name)
        build = cls.root / 'build'; builder.prepare(build); cls.binary = build / 'client'
        probe = build / 'flex/control/sim-visual-stop-native.flex'
        probe.write_bytes((ROOT / 'flex/tests/sim-visual-stop-native.flex').read_bytes())
        subprocess.run([str(builder.COMPILER), str(probe), '-o', str(cls.root / 'probe')], check=True, timeout=20)
        subprocess.run([str(cls.root / 'probe')], check=True, timeout=10)
        model = cls.root / 'model'; model.mkdir(); (model / 'kernels').mkdir()
        (model / 'weights.bin').write_bytes(b'weights')
        policy = model / 'policy'; policy.write_text('''#!/usr/bin/python3
import os,struct
os.write(3,b'VCPOL001')
def read(n):
 b=b''
 while len(b)<n:
  x=os.read(3,n-len(b))
  if not x: raise EOFError()
  b+=x
 return b
try:
 while True:
  read((21168+7+128)*4); speed=-.2 if os.environ.get('STUB_MODE')=='reverse' else .2; os.write(3,struct.pack('<130f',0,speed,*([0]*128)))
except EOFError: pass
'''); policy.chmod(0o755)
        kernels = {}
        for i in range(5):
            path = model / 'kernels' / f'k{i}'; path.write_bytes(str(i).encode()); kernels[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        (model / 'receipt.json').write_text(json.dumps({'weightsSHA256': sha(model / 'weights.bin'), 'binarySHA256': sha(policy), 'kernels': kernels}))
        simulator = cls.root / 'simulator'; simulator.write_text('''#!/usr/bin/python3
import json,os,struct,sys
from pathlib import Path
step=100; mode=os.environ.get('STUB_MODE','textured'); output=Path(os.environ['STUB_COMMANDS']); n=0
open(sys.argv[sys.argv.index('--record')+1],'w').write('stub trace\\n')
row=b''.join(bytes([50,50,50]) * 32 + bytes([170,170,170]) * 32 for _ in range(10))
rgb=row*480
if mode=='flat': rgb=bytes([100])*640*480*3
def read(n):
 b=b''
 while len(b)<n:
  x=os.read(3,n-len(b))
  if not x: raise EOFError()
  b+=x
 return b
try:
 while True:
  command,seq,steer,speed,hold,_,task,_=struct.unpack('<8q',read(64))
  with output.open('a') as f: f.write(json.dumps([command,seq,steer,speed,hold])+'\\n')
  owner=0; valid=True; ack=0; drive=[0,0,90]
  if command==2:
   n+=1; step+=hold; ack=1; drive=[int(speed*60/1000)]*2+[90+int(int(steer/10)*45/100)]
   if mode=='stale' and n==4: step-=1
   if mode=='drive' and n==4: drive[0]=99
  elif command==3:
   owner=2; valid=False; ack=6 if mode=='badstop' else 7
  x={'schema':'puppybot.physical-agent.v1','sequence':seq,'owner':owner,'ack':ack,'imageValid':valid,'rgbDetections':0 if valid else None,'totalSteps':step,'cameraFrame':step if valid else -1,'cameraDriving':valid,'cameraStill':valid,'driveCommand':drive,'jointTicks':[1,2,3,4]}
  data=(json.dumps(x)+'\\n').encode(); wire=struct.pack('<4q',len(data),640*480*3,seq,0)+data+(rgb if valid else bytes(640*480*3))
  while wire: wire=wire[os.write(3,wire):]
  if command==3: break
except EOFError: pass
'''); simulator.chmod(0o755)
        (cls.root / 'case').write_text('{}'); (cls.root / 'environment').write_bytes(b'fake')

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def run_case(self, mode, enabled):
        parent = Path(tempfile.mkdtemp(dir=self.root)); out = parent / 'run'; commands = parent / 'commands'
        env = dict(os.environ, STUB_MODE=mode, STUB_COMMANDS=str(commands), PUPPYBOT_PHYSICAL_NAV_LIMIT='20', PUPPYBOT_SIM_VISUAL_STOP=str(int(enabled)))
        proc = subprocess.run([str(self.binary), str(self.root / 'simulator'), str(self.root / 'model'), str(self.root / 'case'), str(self.root / 'environment'), str(out), '--allow-zero-contact'], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        wire = [json.loads(x) for x in commands.read_text().splitlines()] if commands.exists() else []
        return proc, out, wire

    def test_opt_in_static_and_low_texture_stop(self):
        for mode, reason in (('textured',2), ('flat',3), ('reverse',2)):
            with self.subTest(mode=mode):
                proc, out, commands = self.run_case(mode, True)
                self.assertEqual(proc.returncode, 0, proc.stderr + '\n' + '\n'.join(p.read_text(errors='replace') for p in out.glob('*.log')))
                result = json.loads((out / 'result.json').read_text())
                self.assertEqual((result['visualStopEnabled'], result['visualStopReason'], result['policyActions']), (True, reason, 9))
                self.assertTrue(result['stopCommandAcknowledged']); self.assertEqual([x[0] for x in commands], [1] + [2]*9 + [3])
                self.assertTrue(all(x[3] < 0 if mode == 'reverse' else x[3] > 0 for x in commands[1:-1]))
                auditor = ROOT / 'flex/tests/audit-sim-visual-stop.py'
                checked = subprocess.run([os.sys.executable, '-I', str(auditor), str(out)], capture_output=True, text=True, timeout=15)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertEqual(json.loads(checked.stdout)['reason'], reason)
                final_image = out / 'actors' / 'visual-1.rgb'; final_image.write_bytes(bytes(21168))
                self.assertNotEqual(subprocess.run([os.sys.executable, '-I', str(auditor), str(out)], capture_output=True, timeout=15).returncode, 0)

    def test_disabled_uses_same_binary_and_limit(self):
        proc, out, commands = self.run_case('textured', False)
        self.assertEqual(proc.returncode, 0, proc.stderr + '\n' + '\n'.join(p.read_text(errors='replace') for p in out.glob('*.log')))
        result = json.loads((out / 'result.json').read_text())
        self.assertEqual((result['visualStopEnabled'], result['visualStopReason'], result['policyActions']), (False, 0, 20))
        self.assertEqual([x[0] for x in commands], [1] + [2]*20 + [3])

    def test_matched_disabled_and_enabled_prefix(self):
        original, left, left_wire = self.run_case('textured', False)
        experimental, right, right_wire = self.run_case('textured', True)
        self.assertEqual((original.returncode, experimental.returncode), (0, 0))
        self.assertEqual(left_wire[:10], right_wire[:10])
        self.assertEqual(right_wire[10][0], 3)
        self.assertEqual(left_wire[10][0], 2)
        for seq in range(1, 10):
            for ext in ('rgb', 'feedback', 'hidden', 'action'):
                name = f'actor-{seq}.{ext}'
                self.assertEqual((left / 'actors' / name).read_bytes(), (right / 'actors' / name).read_bytes())
        left_rows = [json.loads(x) for x in (left / 'physical-agent.jsonl').read_text().splitlines()]
        right_rows = [json.loads(x) for x in (right / 'physical-agent.jsonl').read_text().splitlines()]
        self.assertEqual(left_rows[:10], right_rows[:10])

    def test_failure_does_not_report_stop_ack(self):
        for mode in ('stale', 'drive', 'badstop'):
            with self.subTest(mode=mode):
                proc, out, _ = self.run_case(mode, True)
                self.assertNotEqual(proc.returncode, 0); self.assertFalse((out / 'result.json').exists())


if __name__ == '__main__': unittest.main()
