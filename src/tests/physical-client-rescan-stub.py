# Simulator-only stopped-rescan integration test, with stub actor/simulator.
# Usage: python3 -I flex/tests/physical-client-rescan-stub.py COMPILED_CLIENT
# The test uses local socketpairs and does not exercise physical motors or GPU.
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


POLICY = '''#!/usr/bin/env python3
import socket,struct
s=socket.socket(fileno=3);s.sendall(b"VCPOL001")
def read(n):
 b=b""
 while len(b)<n:
  v=s.recv(n-len(b))
  if not v: raise EOFError()
  b+=v
 return b
try:
 while True:
  read((21168+7+128)*4);s.sendall(struct.pack("<130f",0.0,0.2,*([0.0]*128)))
except EOFError: pass
'''

SIMULATOR = '''#!/usr/bin/env python3
import json,os,socket,struct,sys
s=socket.socket(fileno=3);step=100;attempts=0;scenario=os.environ['PUPPY_RESCAN_SCENARIO'];commands=[]
open(sys.argv[sys.argv.index('--record')+1],'w').write('stub-trace\\n')
def read(n):
 b=b''
 while len(b)<n:
  v=s.recv(n-len(b))
  if not v: raise EOFError()
  b+=v
 return b
try:
 while True:
  command,seq,steer,speed,hold,_,task,_=struct.unpack('<8q',read(64));commands.append(command)
  if scenario=='transport_eof' and command==6: break
  owner=0;valid=True;ack=0;drive=[0,0,90];detect=0
  if command==2:
   step+=hold;ack=1;throttle=int(speed*60/1000) if abs(speed)>=80 else 0
   drive=[throttle,throttle,90+int(int(steer/10)*45/100)]
  elif command==6:
   attempts+=1;step+=2
   if scenario=='late_target' and attempts==2: owner=1;valid=False;ack=3
   elif scenario=='guard_timeout': step+=2;owner=1;valid=False;ack=3
   elif scenario=='stalled_handoff': step-=2;owner=1;valid=False;ack=3
   else: ack=2
  elif command==7: step+=hold;owner=2;valid=False;ack=5
  elif command==3: owner=2;valid=False;ack=7
  x={'schema':'puppybot.physical-agent.v1','sequence':seq,'step':step,'timeMs':step*20,'owner':owner,'ack':ack,'imageValid':valid,'rgbDetections':detect if valid else None,'totalSteps':step,'cameraFrame':step if valid else -1,'cameraDriving':valid,'cameraStill':valid,'driveCommand':drive,'jointTicks':[1,2,3,4]}
  body=(json.dumps(x)+'\\n').encode();s.sendall(struct.pack('<4q',len(body),640*480*3,seq,0)+body+bytes(640*480*3))
  if command==3: break
except EOFError: pass
finally: open(os.environ['PUPPY_RESCAN_COMMANDS'],'w').write(json.dumps(commands))
'''


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: physical-client-rescan-stub.py COMPILED_CLIENT')
    client = str(Path(sys.argv[1]).resolve())
    project = str(Path(__file__).resolve().parents[2])
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix='puppy-rescan-') as directory:
        root = Path(directory)
        model = root / 'model'; model.mkdir(); (model / 'kernels').mkdir()
        (model / 'weights.bin').write_bytes(b'weights')
        (model / 'policy').write_text(POLICY); (model / 'policy').chmod(0o755)
        kernels = {}
        for i in range(5):
            name = f'kernel{i}'; path = model / 'kernels' / name
            path.write_bytes(name.encode()); kernels[name] = sha(path)
        (model / 'receipt.json').write_text(json.dumps({'weightsSHA256': sha(model / 'weights.bin'),
            'binarySHA256': sha(model / 'policy'), 'memoryWidth': 128, 'kernels': kernels}))
        simulator = root / 'simulator'; simulator.write_text(SIMULATOR); simulator.chmod(0o755)
        case = root / 'case.json'; case.write_text('{}')
        environment = root / 'environment.bin'; environment.write_bytes(b'fake')
        for scenario in ('disabled', 'no_target', 'late_target', 'guard_timeout', 'stalled_handoff', 'transport_eof'):
            out = root / scenario; commands = root / (scenario + '.commands')
            env = dict(os.environ, PUPPY_RESCAN_SCENARIO=scenario, PUPPY_RESCAN_COMMANDS=str(commands),
                       PUPPYBOT_PHYSICAL_NAV_LIMIT='1', PUPPYBOT_PHYSICAL_POLL_LIMIT='1')
            if scenario != 'disabled':
                env['PUPPYBOT_PHYSICAL_GUARDED_RESCAN'] = '1'
            else:
                env.pop('PUPPYBOT_PHYSICAL_GUARDED_RESCAN', None)
            run = subprocess.run([client, str(simulator), str(model), str(case), str(environment), str(out),
                                  '--allow-zero-contact'], env=env, cwd=project, capture_output=True, text=True, timeout=40)
            if scenario == 'transport_eof':
                assert run.returncode != 0 and not (out / 'result.json').exists(), (scenario, run.stdout, run.stderr)
                assert json.loads(commands.read_text()) == [1, 2, 6]
                print(scenario, 'rejected without a result; stop acknowledgement unavailable')
                continue
            assert run.returncode == 0, (scenario, run.stderr)
            result = json.loads((out / 'result.json').read_text()); sent = json.loads(commands.read_text())
            assert json.loads((out / 'inputs.json').read_text())['stoppedRescanEnabled'] == (scenario != 'disabled')
            assert result['policyActions'] == 1 and result['stopCommandAcknowledged'] and result['outcome'] == 'unverified'
            if scenario == 'disabled':
                assert not result['stoppedRescanEnabled'] and sent == [1, 2, 3]
            elif scenario == 'no_target':
                assert result['stoppedRescanAttempts'] == 2 and result['stoppedRescanStopReason'] == 2
                assert result['stoppedRescanStopReasonText'] == 'attempts exhausted'
                assert not result['stoppedRescanHandoff'] and sent == [1, 2, 6, 2, 6, 3]
            elif scenario == 'late_target':
                assert result['stoppedRescanAttempts'] == 2 and result['stoppedRescanStopReason'] == 0
                assert result['stoppedRescanHandoff'] and sent == [1, 2, 6, 2, 6, 7, 3]
            elif scenario == 'guard_timeout':
                assert result['stoppedRescanAttempts'] == 1 and result['stoppedRescanStopReason'] == 4
                assert result['stoppedRescanStopReasonText'] == 'recovery timeout'
                assert not result['stoppedRescanHandoff'] and sent == [1, 2, 6, 3]
            else:
                assert result['stoppedRescanAttempts'] == 1 and result['stoppedRescanStopReason'] == 3
                assert result['stoppedRescanStopReasonText'] == 'protocol error'
                assert not result['stoppedRescanHandoff'] and sent == [1, 2, 6, 3]
            print(scenario, 'passed', result)


if __name__ == '__main__':
    main()
