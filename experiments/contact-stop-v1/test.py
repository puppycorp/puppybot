#!/usr/bin/env python3
"""CPU-only checks for the isolated sustained-contact stop prototype."""
import importlib.util
import json
import shutil
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

PROBE = r'''import "host.flex";
import "contact-stop.flex";
global ve_state=0;global ve_steps=0;global ve_contact=0;
global fail_echo=0;global requests=0;
''' + transform.GLOBALS + r'''
fn ve_step(action) {
    vc_require(!pb_u32(action) && !pb_u32(action+4),"stop request was not zero");
    requests=requests+1;ve_steps=ve_steps+1;pl_print(1,"ZERO_REQUESTED\n");
    let good="{\"controller\":{\"drive\":{\"leftSpeed\":0,\"rightSpeed\":0}}}";
    let bad="{\"controller\":{\"drive\":{\"leftSpeed\":60,\"rightSpeed\":60}}}";
    if fail_echo {ve_state=pj_parse(bad,pl_size(bad));}else {ve_state=pj_parse(good,pl_size(good));}return 0;
}
''' + transform.HOOKS + r'''
fn main(argc,argv) {
    vc_init(argc,argv);vc_require(argc==3,"expected mode and output directory");
    let mode=load64(argv+8);let directory=load64(argv+16);let action=alloc(8);
    vx_contact_guard=alloc(24);vc_require(cs_init(vx_contact_guard,3),"guard init failed");
    let moving="{\"controller\":{\"drive\":{\"leftSpeed\":60,\"rightSpeed\":60}}}";
    ve_state=pj_parse(moving,pl_size(moving));ve_contact=1;ve_steps=144;
    vc_require(!vx_contact_stop_check(directory,action) && !requests,"first sample stopped early");
    vc_require(!vx_contact_stop_check(directory,action) && !requests,"second sample stopped early");
    if pl_equal(mode,"bad-echo") {fail_echo=1;}
    if pl_equal(mode,"horizon") {ve_steps=300;}
    vc_require(vx_contact_stop_check(directory,action) && requests==1,"stop request missing");
    vc_require(vx_contact_stop_reason==1,"wrong contact reason");
    if pl_equal(mode,"horizon") {vc_require(ve_steps==301,"wrong horizon stop count");}
    else {vc_require(ve_steps==145,"wrong normal stop count");}return 0;
}
'''


class ContactStopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='puppy-contact-stop-')
        cls.temp_root = Path(cls.temp.name)
        source = cls.temp_root / 'flex'
        shutil.copytree(ROOT / 'flex', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        control = source / 'control'
        chase = control / 'chase.flex'; main = control / 'main.flex'
        chase_text, main_text = transform.transform(chase.read_text(), main.read_text())
        chase.write_text(chase_text); main.write_text(main_text)
        shutil.copyfile(HERE / 'contact-stop.flex', control / 'contact-stop.flex')
        (control / 'contact-stop-probe.flex').write_text(PROBE)
        for filename, target in (('main.flex', 'control'), ('contact-stop-probe.flex', 'probe')):
            subprocess.run([str(COMPILER), str(control / filename), '-o', str(cls.temp_root / target)],
                           cwd=ROOT, check=True, timeout=120, capture_output=True)
        # Compile the library test against the same copied host imports.
        test = (HERE / 'test.flex').read_text().replace('import "../../flex/control/host.flex";', 'import "host.flex";')
        (control / 'contact-stop-test.flex').write_text(test)
        subprocess.run([str(COMPILER), str(control / 'contact-stop-test.flex'), '-o', str(cls.temp_root / 'test')],
                       cwd=ROOT, check=True, timeout=120, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_probe(self, mode):
        out = Path(tempfile.mkdtemp(prefix='out-', dir=self.temp_root))
        result = subprocess.run([str(self.temp_root / 'probe'), mode, str(out)], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        report = out / 'contact-stop.json'
        return result, json.loads(report.read_text()) if report.exists() else None

    def test_native_guard(self):
        subprocess.run([str(self.temp_root / 'test')], cwd=ROOT, check=True, timeout=15, capture_output=True)

    def test_zero_echo_is_not_a_stop_acknowledgement(self):
        result, report = self.run_probe('normal')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report['reason'], 'sustained_contact')
        self.assertEqual(report['consecutiveContactSamples'], 3)
        self.assertEqual(report['observedActions'], 145)
        self.assertEqual(report['triggerAfterActions'], 144)
        self.assertEqual(report['zeroStopActions'], 1)
        self.assertIs(report['zeroCommandEchoObserved'], True)
        self.assertIs(report['stopCommandAcknowledged'], False)
        self.assertIs(report['goalGameCompleted'], False)

    def test_last_horizon_feedback_gets_zero_stop_action(self):
        result, report = self.run_probe('horizon')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report['triggerAfterActions'], 300)
        self.assertEqual(report['observedActions'], 301)
        self.assertEqual(report['zeroStopActions'], 1)
        self.assertIs(report['goalGameCompleted'], False)

    def test_bad_echo_does_not_claim_stop(self):
        result, report = self.run_probe('bad-echo')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ZERO_REQUESTED', result.stdout)
        self.assertIsNone(report)

    def test_report_failure_occurs_after_zero_request(self):
        out = self.temp_root / 'missing-directory'
        result = subprocess.run([str(self.temp_root / 'probe'), 'normal', str(out)], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ZERO_REQUESTED', result.stdout)

    def test_transform_is_opt_in_and_single_use(self):
        chase = (ROOT / 'flex/control/chase.flex').read_text()
        main = (ROOT / 'flex/control/main.flex').read_text()
        new_chase, new_main = transform.transform(chase, main)
        self.assertIn('if !vw_contact_stop || !vx_contact_stop_check', new_chase)
        self.assertIn('goalGameCompleted', new_chase)
        self.assertIn('ve_steps==vw_horizon {vx_contact_stop_check(directory,action);}', new_chase)
        self.assertIn('--contact-stop', new_main)
        with self.assertRaises(ValueError):
            transform.transform(new_chase, new_main)


if __name__ == '__main__':
    unittest.main()
