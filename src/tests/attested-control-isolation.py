#!/usr/bin/env python3
"""CPU tests for the isolated real-control instrumentation build."""
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('prepare', ROOT / 'flex/tests/prepare-attested-control.py')
prepare = importlib.util.module_from_spec(spec); spec.loader.exec_module(prepare)
spec = importlib.util.spec_from_file_location('actor_audit', ROOT / 'datasets/visual-control/chase-v1/levels/audit-actor-attestation.py')
actor_audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(actor_audit)
spec = importlib.util.spec_from_file_location('argv_audit', ROOT / 'flex/tests/audit-attested-argv.py')
argv_audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(argv_audit)


def read_argv(path):
    data = path.read_bytes()
    if data[:8] != b'PBARGV01':
        raise ValueError('invalid argv journal')
    at = 8; records = []
    while at < len(data):
        if len(data) - at < 16:
            raise ValueError('truncated record')
        kind, count = struct.unpack_from('<2q', data, at); at += 16
        if kind == 2 and count == 0:
            if at != len(data):
                raise ValueError('trailing argv data')
            records.append((kind, [])); break
        if kind not in (0, 1) or not 1 <= count <= 128:
            raise ValueError('invalid record')
        args = []
        for _ in range(count):
            if len(data) - at < 8:
                raise ValueError('truncated size')
            size, = struct.unpack_from('<q', data, at); at += 8
            if size < 0 or size > len(data) - at:
                raise ValueError('invalid argument size')
            args.append(data[at:at + size]); at += size
        records.append((kind, args))
    return records


class IsolatedControlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.build = cls.root / 'build-copy'
        prepare.prepare(cls.build)
        cls.binary = cls.build / 'control-attested'

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_build_isolated_and_unmodified_source(self):
        report = json.loads((self.build / 'build.json').read_text())
        self.assertEqual(report['binarySHA256'], prepare.digest(self.binary))
        active = (ROOT / 'flex/control/chase.flex').read_text()
        isolated = (self.build / 'flex/control/chase.flex').read_text()
        self.assertNotIn('pa_record(attestation', active)
        self.assertIn('pa_record(attestation,ve_steps,ve_sequence', isolated)
        self.assertIn('ve_image,ve_policy_input,ve_policy_output,action', isolated)

    def test_actual_control_records_argv_before_failed_policy_handshake(self):
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            root = Path(tmp); model = root / 'model'; model.mkdir(); (model / 'kernels').mkdir()
            (model / 'weights.bin').write_bytes(b'weights')
            policy = model / 'policy'
            policy.write_text('#!/usr/bin/python3\nimport os\nos.write(3,b"BADPOL00")\n')
            policy.chmod(0o755)
            kernels = {}
            for i in range(5):
                p = model / 'kernels' / f'{i}.hip'; p.write_bytes(f'kernel {i}'.encode())
                kernels[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
            receipt = {'weightsSHA256': prepare.digest(model / 'weights.bin'),
                       'binarySHA256': prepare.digest(policy), 'kernels': kernels}
            (model / 'receipt.json').write_text(json.dumps(receipt))
            output = root / 'run with spaces'
            command = [str(self.binary), 'run', '--chase', '--fetch', '--policy', str(model),
                       '--output', str(output), '--episodes', '1', '--horizon', '1', '--seed', '7']
            completed = subprocess.run(command, cwd=root, capture_output=True, timeout=10)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(b'invalid policy handshake', completed.stderr)
            records = read_argv(output / 'argv.bin')
            self.assertEqual(records[0], (0, [os.fsencode(arg) for arg in command]))
            self.assertEqual(len(records), 2)
            kind, args = records[1]
            self.assertEqual(kind, 1)
            self.assertEqual(args[0], os.fsencode(output / 'policy/policy'))
            self.assertEqual(args[1], os.fsencode(output / 'policy/weights.bin'))
            self.assertEqual(args[-1], b'3')
            self.assertFalse((output / '7').exists(), 'simulator must not start in this test')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                argv_audit.audit(output / 'argv.bin')

    def test_build_refuses_existing_destination(self):
        before = prepare.digest(self.binary)
        with self.assertRaises(FileExistsError):
            prepare.prepare(self.build)
        self.assertEqual(prepare.digest(self.binary), before)

    def test_argv_auditor_rejects_partial_and_preserves_raw_bytes(self):
        args = [b'program', b'', b'white space', b'`$()\xff']
        header = b'PBARGV01' + struct.pack('<2q', 0, len(args))
        record = b''.join(struct.pack('<q', len(arg)) + arg for arg in args)
        footer = struct.pack('<2q', 2, 0)
        path = self.root / 'synthetic-argv.bin'
        for data in (header + record, header + record + footer[:-1], header + record + footer + b'x'):
            path.write_bytes(data)
            with self.assertRaises(ValueError): argv_audit.audit(path)
        path.write_bytes(header + record + footer)
        report = argv_audit.audit(path)
        import base64
        self.assertEqual([base64.b64decode(v) for v in report['records'][0]['argvBase64']], args)

    def test_intervention_options_are_rejected_before_policy_spawn(self):
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            root = Path(tmp)
            options = (['--search-cue'], ['--hide-carry'], ['--blackout'], ['--straight-bias', '10'],
                       ['--ensemble', str(root / 'other')], ['--chase-forward'])
            for index, flags in enumerate(options):
                output = root / str(index)
                command = [str(self.binary), 'run', '--chase', '--fetch', '--policy', str(root / 'unused'),
                           '--output', str(output), '--episodes', '1', '--horizon', '1'] + flags
                done = subprocess.run(command, cwd=root, capture_output=True, timeout=10)
                with self.subTest(flags=flags):
                    self.assertNotEqual(done.returncode, 0)
                    self.assertIn(b'attested build supports only', done.stderr)
                    self.assertFalse((output / 'argv.bin').exists())

    def test_real_control_boundary_with_cpu_stub_peers(self):
        # Replay one existing, previously recorded simulator observation through
        # the instrumented real control process. Neither stub uses a GPU.
        saved = ROOT / 'build/flex/sim/levels-v2/pitch82/search-dagger-l35-4workers/selection-L5/student-s2/0/7800001'
        self.assertTrue((saved / 'decisions.jsonl').exists(), 'saved L5 observation fixture unavailable')
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            root = Path(tmp); initial = json.loads((saved / 'initial.json').read_text())
            first = json.loads((saved / 'decisions.jsonl').read_text().splitlines()[0])
            (root / 'initial.json').write_text(json.dumps(initial))
            (root / 'first.json').write_text(json.dumps(first))
            simulator = root / 'build/flex/control/simulator'; simulator.parent.mkdir(parents=True)
            simulator.write_text('''#!/usr/bin/python3
import json,os,struct
from pathlib import Path
r=Path(os.environ['ATTEST_STUB_ROOT']); (r/'sim-started').write_text('yes'); a=json.loads((r/'initial.json').read_text()); b=json.loads((r/'first.json').read_text())['state']
def read(n):
 d=b''
 while len(d)<n:
  x=os.read(3,n-len(d))
  if not x: raise EOFError()
  d+=x
 return d
try:
 while True:
  command,sequence,*_=struct.unpack('<8q',read(64)); open(r/'sim-commands','a').write(str(command)+'\\n')
  if command==3: break
  state=b if command==2 else a
  data=(json.dumps(state,separators=(',',':'))+'\\n').encode()
  wire=struct.pack('<4q',len(data),640*480*3,sequence,0)+data+bytes(640*480*3)
  while wire: wire=wire[os.write(3,wire):]
except EOFError: pass
''')
            simulator.chmod(0o755)
            model = root / 'model'; model.mkdir(); (model / 'kernels').mkdir()
            (model / 'weights.bin').write_bytes(b'weights')
            policy = model / 'policy'
            policy.write_text('''#!/usr/bin/python3
import json,os,struct
from pathlib import Path
r=Path(os.environ['ATTEST_STUB_ROOT']); os.write(3,b'VCPOL001')
def read(n):
 d=b''
 while len(d)<n:
  x=os.read(3,n-len(d))
  if not x: raise EOFError()
  d+=x
 return d
try:
 data=read((21168+7+128)*4); (r/'peer-input.bin').write_bytes(data)
 action=json.loads((r/'first.json').read_text())['action']
 os.write(3,struct.pack('<130f',*action,*([0.0]*128)))
 while os.read(3,1): pass
except EOFError: pass
''')
            policy.chmod(0o755)
            kernels = {}
            for i in range(5):
                p = model / 'kernels' / f'{i}.hip'; p.write_bytes(f'kernel {i}'.encode()); kernels[p.name] = prepare.digest(p)
            (model / 'receipt.json').write_text(json.dumps({'weightsSHA256': prepare.digest(model / 'weights.bin'),
                'binarySHA256': prepare.digest(policy), 'kernels': kernels}))
            scene = root / 'catalog/0'; scene.mkdir(parents=True)
            for name in ('case.json', 'environment.bin'):
                shutil.copyfile(saved / 'scene' / name, scene / name)
            shutil.copyfile(ROOT / 'build/flex/sim/expanded-rooms-v1/scenes/15/1/layout.json', scene / 'layout.json')
            output = root / 'result'; env = os.environ.copy(); env['ATTEST_STUB_ROOT'] = str(root)
            command = [str(self.binary), 'run', '--chase', '--fetch', '--policy', str(model), '--scene-catalog',
                       str(scene.parent), '--output', str(output), '--episodes', '1', '--horizon', '1',
                       '--seed', '7800001', '--level', '5', '--lean', '--wheel-odometry']
            done = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=15)
            logs = [str(p.relative_to(output)) + ': ' + p.read_text(errors='replace') for p in output.rglob('*.log')]
            if (root / 'sim-commands').exists(): logs.append('commands: ' + (root / 'sim-commands').read_text())
            logs.append('sim-started=' + str((root / 'sim-started').exists()))
            if (output / 'argv.bin').exists(): logs.append('argv=' + repr(read_argv(output / 'argv.bin')))
            self.assertEqual(done.returncode, 0, done.stderr.decode(errors='replace') + '\n' + '\n'.join(logs))
            journal = (output / '7800001/actor-attestation.bin').read_bytes()
            input_at = 56 + 24 + 21168; input_size = (21168 + 7 + 128) * 4
            self.assertEqual(journal[input_at:input_at + input_size], (root / 'peer-input.bin').read_bytes())
            self.assertEqual(journal[-16:-8], b'PBDONE01')
            checked = actor_audit.audit(output / '7800001/actor-attestation.bin', output / '7800001')
            self.assertEqual(checked['status'], 'actor_journal_internally_consistent')
            argv = read_argv(output / 'argv.bin')
            self.assertEqual(argv[0], (0, [os.fsencode(v) for v in command]))
            self.assertEqual([record[0] for record in argv[1:]], [1, 1, 2])
            self.assertEqual(argv_audit.audit(output / 'argv.bin')['status'], 'completed_argv_journal')


if __name__ == '__main__':
    unittest.main()
