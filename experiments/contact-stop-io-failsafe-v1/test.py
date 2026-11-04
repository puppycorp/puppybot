#!/usr/bin/env python3
"""CPU socket tests for the isolated virtual-simulator failure-stop hook."""
import importlib.util
import json
import math
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contact = load('contact_stop', ROOT / 'experiments/contact-stop-v1/transform.py')
protocol = load('contact_protocol_test', ROOT / 'experiments/contact-stop-v1/protocol-test.py')
transform = load('io_stop_transform', HERE / 'transform.py')

WAIT_PROBE = r'''import "host.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"expected fd and child timing");
    let fd=pl_integer(load64(argv+8),pl_size(load64(argv+8)));let delay=pl_integer(load64(argv+16),pl_size(load64(argv+16)));
    let pid=syscall(57,0,0,0,0,0,0);vc_require(pid>=0,"fork failed");
    if !pid {syscall(3,fd,0,0,0,0,0);syscall(7,0,0,delay,0,0,0);syscall(60,0,0,0,0,0,0);}
    vc_fault_stop_enabled=1;vc_fault_stop_fd=fd;vc_fault_stop_pid=pid;vc_fault_stop_sequence=5;
    vc_fault_stop();vc_fault_stop();let status=alloc(8);let live=syscall(61,pid,status,1,0,0,0);
    if !live {syscall(62,pid,9,0,0,0,0);syscall(61,pid,status,0,0,0,0);}return 0;
}
'''


class FailureStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='puppy-io-stop-')
        cls.root = Path(cls.temp.name)
        shutil.copytree(ROOT / 'flex', cls.root / 'flex', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        control = cls.root / 'flex/control'
        chase, main = contact.transform((control / 'chase.flex').read_text(), (control / 'main.flex').read_text())
        (control / 'chase.flex').write_text(chase)
        host, environment, main = transform.transform((control / 'host.flex').read_text(),
                                                       (control / 'environment.flex').read_text(), main)
        for path, value in (('host.flex', host), ('environment.flex', environment), ('main.flex', main)):
            (control / path).write_text(value)
        shutil.copyfile(ROOT / 'experiments/contact-stop-v1/contact-stop.flex', control / 'contact-stop.flex')
        original = '    let action=alloc(8);pb_put32(action,0);'
        hook = ('    vc_fault_stop_enabled=!pl_equal(mode,"no-failsafe");vc_fault_stop_ready=1;'
                'vc_fault_stop_fd=fd;vc_fault_stop_pid=syscall(39,0,0,0,0,0,0);'
                'vc_require(!syscall(72,fd,4,2048,0,0,0),"nonblock failed");\n' + original)
        (control / 'probe.flex').write_text(protocol.PROBE.replace(original, hook))
        (control / 'wait-probe.flex').write_text(WAIT_PROBE)
        compiler = ROOT / 'build/flex/control/compiler'
        for source, binary in (('main.flex', 'control'), ('probe.flex', 'probe'), ('wait-probe.flex', 'wait-probe')):
            result = subprocess.run([str(compiler), str(control / source), '-o', str(cls.root / binary)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise AssertionError(result.stderr)
        # Injected time and I/O outcomes exercise a clock failure and endless
        # EINTR/partial progress deterministically, without wall-clock sleeps.
        for mode in ('clock-fail', 'eintr', 'trickle'):
            if mode == 'clock-fail':
                changed = host.replace('fn vc_fault_io_now() {return pl_now();}',
                                       'fn vc_fault_io_now() {return -1;}')
            else:
                changed = host.replace('fn vc_fault_io_now() {return pl_now();}',
                                       'global injected_now=0;fn vc_fault_io_now() {injected_now=injected_now+1000;return injected_now;}')
                marker = 'let n=0;if reading {n=syscall(0,fd,data+at,size-at,0,0,0);}'
                changed = changed.replace(marker, 'let n=0;if bounded {n=' + ('-4' if mode == 'eintr' else '1') + ';}else if reading {n=syscall(0,fd,data+at,size-at,0,0,0);}')
                if marker in changed: raise AssertionError('I/O injection did not apply')
            if changed == host: raise AssertionError('clock injection did not apply')
            (control / 'host.flex').write_text(changed)
            result = subprocess.run([str(compiler), str(control / 'probe.flex'), '-o', str(cls.root / ('probe-' + mode))],
                                    cwd=ROOT, capture_output=True, text=True, timeout=120)
            if result.returncode: raise AssertionError(result.stderr)
        (control / 'host.flex').write_text(host)
        cls.state = protocol.RealEnvironmentProtocolTests.state if hasattr(protocol.RealEnvironmentProtocolTests, 'state') else {
            'step': 100, 'totalSteps': 100, 'pose': [0.0, 0.0, 0.0], 'physicsFault': 0,
            'vehicle': {'queryFault': 0}, 'trainingOracle': {'enabled': False, 'queries': 0},
            'gripper': {'held': False, 'grasps': 0, 'releases': 0},
            'discovery': {'suppliedMap': False, 'worldPoseInput': False, 'scans': 0, 'freeCells': 0, 'occupiedCells': 0},
            'camera': {'pose': 'driving', 'armSettled': True},
            'case': {'passed': False, 'perception': {'frameId': 100}},
            'jointAnglesRad': [0.0, 0.0, 0.0, 0.0], 'findReturn': {'consumedIndex': -1},
            'controller': {'drive': {'leftSpeed': 0, 'rightSpeed': 0, 'steeringAngleDeg': 90}},
        }
        cls.fixture = cls.root / 'fixture.json'
        cls.fixture.write_text(json.dumps(cls.state))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def exercise(self, mode):
        directory = Path(tempfile.mkdtemp(dir=self.root))
        peer, child = socket.socketpair(); peer.settimeout(8)
        binary = 'probe-' + mode if mode in ('clock-fail', 'eintr', 'trickle') else 'probe'
        process = subprocess.Popen([str(self.root / binary), str(child.fileno()), str(self.fixture),
                                    str(directory), mode], cwd=ROOT, pass_fds=(child.fileno(),),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child.close(); requests = []; step = 100; waiting_at = None; delay = None
        try:
            while True:
                try: raw = protocol.read_exact(peer, 64)
                except EOFError: break
                command, seq, steer, speed, hold, _, task, _ = struct.unpack('<8q', raw)
                requests.append((command, seq, steer, speed, hold, task))
                if command == 3:
                    if waiting_at is not None: delay = time.monotonic() - waiting_at
                    break
                self.assertEqual(command, 2)
                if seq == 2 and mode == 'timeout':
                    waiting_at = time.monotonic()
                    continue
                step += hold
                row = json.loads(json.dumps(self.state))
                if seq == 2 and mode in ('stale-drive', 'no-failsafe'): step -= 1
                row['step'] = row['totalSteps'] = step
                row['case']['perception']['frameId'] = step
                throttle = math.trunc(speed * 60 / 1000) if abs(speed) >= 80 else 0
                row['controller']['drive'].update(leftSpeed=throttle, rightSpeed=throttle, steeringAngleDeg=90)
                body = json.dumps(row).encode()
                if seq == 2 and mode == 'bad-header':
                    peer.sendall(struct.pack('<4q', len(body), 640 * 480 * 3, seq + 1, 1))
                    continue
                peer.sendall(struct.pack('<4q', len(body), 640 * 480 * 3, seq, 1) + body + bytes(640 * 480 * 3))
        finally:
            peer.close()
            try: stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate(); raise
        return process.returncode, requests, stderr, (directory / 'contact-stop.json').exists(), delay

    def test_stale_malformed_and_timeout_request_a_bounded_stop(self):
        for mode in ('stale-drive', 'bad-header', 'timeout'):
            with self.subTest(mode=mode):
                code, requests, stderr, report, delay = self.exercise(mode)
                self.assertNotEqual(code, 0)
                self.assertTrue(requests, stderr)
                self.assertEqual(requests[-1][:4], (3, 3, 0, 0))
                self.assertIn('stop unverified', stderr)
                self.assertFalse(report)
                if mode == 'timeout': self.assertTrue(4.0 <= delay <= 7.0, delay)

    def test_disabled_fault_path_does_not_send_stop(self):
        code, requests, stderr, report, _ = self.exercise('no-failsafe')
        self.assertNotEqual(code, 0)
        self.assertEqual([row[0] for row in requests], [2, 2], stderr)
        self.assertNotIn('failure stop request', stderr)
        self.assertFalse(report)

    def test_clock_failure_and_repeated_progress_or_eintr_fail_closed(self):
        for mode in ('clock-fail', 'eintr', 'trickle'):
            with self.subTest(mode=mode):
                started = time.monotonic()
                code, requests, stderr, report, _ = self.exercise(mode)
                self.assertNotEqual(code, 0)
                self.assertEqual(requests[-1][:4], (3, 2, 0, 0))
                self.assertIn('clock failure', stderr)
                self.assertIn('stop unverified', stderr)
                self.assertFalse(report)
                self.assertLess(time.monotonic() - started, 2.0)

    def test_wait_is_bounded_and_fault_stop_is_latched(self):
        for delay, expected in ((20, 'child exited'), (1000, 'child exit not observed')):
            with self.subTest(delay=delay):
                peer, child = socket.socketpair(); peer.settimeout(3); started = time.monotonic()
                process = subprocess.Popen([str(self.root / 'wait-probe'), str(child.fileno()), str(delay)],
                                           cwd=ROOT, pass_fds=(child.fileno(),), stderr=subprocess.PIPE, text=True)
                child.close()
                try:
                    raw = protocol.read_exact(peer, 64)
                    self.assertEqual(struct.unpack('<8q', raw)[:4], (3, 6, 0, 0))
                    self.assertEqual(peer.recv(64), b'')
                    _, stderr = process.communicate(timeout=2)
                finally:
                    peer.close()
                    if process.poll() is None: process.kill(); process.wait()
                self.assertEqual(process.returncode, 0, stderr)
                self.assertIn(expected, stderr)
                self.assertIn('stop unverified', stderr)
                self.assertLess(time.monotonic() - started, 2.0)


if __name__ == '__main__':
    unittest.main()
