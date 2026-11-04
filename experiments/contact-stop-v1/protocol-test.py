#!/usr/bin/env python3
"""CPU real environment/protocol functions with a fake socket peer."""
import importlib.util
import json
import math
import shutil
import socket
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMPILER = ROOT / 'build/flex/control/compiler'
spec = importlib.util.spec_from_file_location('contact_stop_transform', HERE / 'transform.py')
transform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transform)

PROBE = r'''import "environment.flex";
import "contact-stop.flex";
''' + transform.GLOBALS + transform.HOOKS + r'''
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==5,"expected peer fd, fixture, output and mode");
    let fd=pl_integer(load64(argv+8),pl_size(load64(argv+8)));vc_require(!pl_bad_number && fd>=0,"invalid peer fd");
    let fixture=load64(argv+16);let directory=load64(argv+24);let mode=load64(argv+32);
    ve_open_buffers();ve_process=alloc(16);store64(ve_process+8,fd);ve_lean=1;ve_task=3;
    ve_state=vc_json_file(fixture);ve_check(1);ve_pose_read(ve_state,ve_pose);vc_copy(ve_initial_pose,ve_pose,24);
    ve_journal=syscall(2,vc_path(directory,"decisions.jsonl"),0x800c1,384,0,0,0);vc_require(ve_journal>=0,"cannot open journal");
    vx_contact_guard=alloc(24);vc_require(cs_init(vx_contact_guard,3),"guard init failed");
    vc_require(syscall(72,fd,1,0,0,0,0)>=0 && load64(ve_process+8)==fd,"peer fd unavailable");
    let action=alloc(8);pb_put32(action,0);pb_put32(action+4,0x3f800000);let i=0;
    while i<3 {
        ve_step(action);
        if !pl_equal(mode,"disabled") {
            let stopped=vx_contact_stop_check(directory,action);
            if i<2 {vc_require(!stopped,"stopped too early");}else {vc_require(stopped,"missed sustained contact");}
        }
        i=i+1;
    }
    syscall(3,ve_journal,0,0,0,0,0);return 0;
}
'''


def read_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise EOFError('peer closed')
        data.extend(part)
    return bytes(data)


class RealEnvironmentProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='puppy-contact-protocol-')
        cls.tmp = Path(cls.temp.name)
        control = cls.tmp / 'flex' / 'control'
        shutil.copytree(ROOT / 'flex', cls.tmp / 'flex', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        shutil.copyfile(HERE / 'contact-stop.flex', control / 'contact-stop.flex')
        (control / 'contact-protocol-probe.flex').write_text(PROBE)
        subprocess.run([str(COMPILER), str(control / 'contact-protocol-probe.flex'), '-o', str(cls.tmp / 'probe')],
                       cwd=ROOT, check=True, capture_output=True, timeout=120)
        cls.state = {
            'step': 100, 'totalSteps': 100, 'pose': [0.0, 0.0, 0.0],
            'physicsFault': 0, 'vehicle': {'queryFault': 0},
            'trainingOracle': {'enabled': False, 'queries': 0},
            'gripper': {'held': False, 'grasps': 0, 'releases': 0},
            'discovery': {'suppliedMap': False, 'worldPoseInput': False,
                          'scans': 0, 'freeCells': 0, 'occupiedCells': 0},
            'camera': {'pose': 'driving', 'armSettled': True},
            'case': {'passed': False, 'perception': {'frameId': 100}},
            'jointAnglesRad': [0.0, 0.0, 0.0, 0.0],
            'findReturn': {'consumedIndex': -1},
            'controller': {'drive': {'leftSpeed': 0, 'rightSpeed': 0, 'steeringAngleDeg': 90}},
        }
        cls.fixture = cls.tmp / 'fixture.json'
        cls.fixture.write_text(json.dumps(cls.state))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, mode):
        out = Path(tempfile.mkdtemp(prefix='case-', dir=self.tmp)); requests = []
        peer, child = socket.socketpair(); peer.settimeout(15)
        process = subprocess.Popen([str(self.tmp / 'probe'), str(child.fileno()), str(self.fixture), str(out), mode],
                                   cwd=ROOT, pass_fds=(child.fileno(),), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        child.close(); step = 100
        try:
            while True:
                try:
                    raw = read_exact(peer, 64)
                except EOFError:
                    break
                command, seq, steer, speed, hold, _, task, _ = struct.unpack('<8q', raw)
                requests.append((command, seq, steer, speed, hold, task))
                self.assertEqual((command, hold, task), (2, 10, 3))
                step += hold
                state = json.loads(json.dumps(self.state))
                zero = speed == 0
                if (zero and mode == 'stale') or (seq == 2 and mode == 'stale-drive'): step -= 1
                state['step'] = state['totalSteps'] = step
                state['case']['perception']['frameId'] = step
                throttle = math.trunc(speed * 60 / 1000) if abs(speed) >= 80 else 0
                angle = 90 + math.trunc(math.trunc(steer / 10) * 45 / 100)
                if zero and mode == 'bad-echo': throttle = 60
                state['controller']['drive'].update(leftSpeed=throttle, rightSpeed=throttle, steeringAngleDeg=angle)
                body = json.dumps(state).encode()
                received_seq = seq + 1 if zero and mode == 'wrong-sequence' else seq
                try:
                    peer.sendall(struct.pack('<4q', len(body), 640 * 480 * 3, received_seq, 0 if zero else 1) +
                                 body + bytes(640 * 480 * 3))
                except BrokenPipeError:
                    if mode != 'wrong-sequence' or not zero:
                        raise
                    break
        finally:
            peer.close()
            try:
                stdout, stderr = process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()
                raise
        report = out / 'contact-stop.json'
        journal = out / 'decisions.jsonl'
        return process.returncode, requests, json.loads(report.read_text()) if report.exists() else None, journal.read_bytes(), stderr

    def test_disabled_matches_enabled_until_zero(self):
        disabled = self.run_case('disabled'); enabled = self.run_case('enabled')
        self.assertEqual(disabled[0], 0, disabled[4]); self.assertEqual(enabled[0], 0, enabled[4])
        self.assertEqual(disabled[1], enabled[1][:3])
        self.assertEqual(len(disabled[1]), 3); self.assertEqual(len(enabled[1]), 4)
        self.assertEqual(enabled[1][-1][2:4], (0, 0))
        self.assertIsNone(disabled[2]); self.assertIs(enabled[2]['zeroCommandEchoObserved'], True)
        self.assertIs(enabled[2]['stopCommandAcknowledged'], False)
        self.assertEqual(disabled[3].splitlines(), enabled[3].splitlines()[:3])

    def test_invalid_stop_responses_do_not_publish_success(self):
        for mode in ('bad-echo', 'stale', 'wrong-sequence'):
            with self.subTest(mode=mode):
                code, requests, report, _, _ = self.run_case(mode)
                self.assertNotEqual(code, 0); self.assertEqual(requests[-1][2:4], (0, 0)); self.assertIsNone(report)

    def test_stale_driving_response_fails_before_guard_can_stop(self):
        code, requests, report, _, _ = self.run_case('stale-drive')
        self.assertNotEqual(code, 0)
        self.assertEqual(len(requests), 2)
        self.assertNotEqual(requests[-1][3], 0)
        self.assertIsNone(report)


if __name__ == '__main__':
    unittest.main()
