#!/usr/bin/env python3
"""Exercise actual simulator receive and synthetic contact suppression over a socket."""
import importlib.util
import json
import socket
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('visual_protocol_build', HERE / 'build.py')
build = importlib.util.module_from_spec(spec); spec.loader.exec_module(build)

PROBE = r'''import "environment.flex";
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"expected peer fd and mode");
    let fd=pl_integer(load64(argv+8),pl_size(load64(argv+8)));
    vc_require(!pl_bad_number && fd>=0,"invalid peer fd");
    ve_open_buffers();ve_process=alloc(16);store64(ve_process+8,fd);ve_sequence=1;
    ve_visual_trial_zero_contact=pl_equal(load64(argv+16),"zero");
    ve_receive();
    if ve_visual_trial_zero_contact {
        vc_require(ve_contact==0 && pb_u32(ve_feedback+20)==0,"contact ablation failed");
    } else {
        vc_require(ve_contact==1 && pb_u32(ve_feedback+20)==0x3f800000,"raw contact missing");
    }
    vc_require(pb_u32(ve_feedback+8)==0x3f19999a && pb_u32(ve_feedback+12)==0x3f19999a,
               "wheel feedback changed");
    return 0;
}
'''


class ContactAblationProtocolTest(unittest.TestCase):
    def test_receive_forces_only_contact_feedback_to_zero(self):
        with tempfile.TemporaryDirectory(prefix='visual-ablation-protocol-') as temp:
            root = Path(temp); candidate = root / 'build'; build.build(candidate)
            source = candidate / 'flex-source/control/visual-ablation-probe.flex'; source.write_text(PROBE)
            subprocess.run([str(build.COMPILER), str(source), '-o', str(root / 'probe')],
                           cwd=ROOT, check=True, capture_output=True, timeout=120)
            for mode in ('normal', 'zero'):
                with self.subTest(mode=mode):
                    parent, child = socket.socketpair()
                    process = subprocess.Popen([str(root / 'probe'), str(child.fileno()), mode],
                                               cwd=ROOT, pass_fds=(child.fileno(),),
                                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    child.close()
                    body = json.dumps({'controller': {'drive': {'leftSpeed': 60, 'rightSpeed': 60,
                                                                 'steeringAngleDeg': 90}}}).encode()
                    try:
                        parent.sendall(struct.pack('<4q', len(body), 640 * 480 * 3, 1, 1) +
                                       body + bytes(640 * 480 * 3))
                    finally:
                        parent.close()
                    try:
                        stdout, stderr = process.communicate(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.communicate(); raise
                    self.assertEqual(process.returncode, 0, stderr)


if __name__ == '__main__':
    unittest.main()
