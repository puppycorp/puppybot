#!/usr/bin/env python3
"""Exercise actual trainer host batch/loss logic without the GPU backward graph."""
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('trainer source no longer matches the probe anchors')
    return source.replace(old, new, 1)


def host_source(source):
    source = once(source, 'fn main(argc,argv) {', 'fn pt_original_train_main(argc,argv) {')
    source = once(source, 'fn pt_loss(training,rate) {', 'fn pt_loss_host(training,rate) {')
    source = once(source, '    vp_execute();if training {pt_zero_grad();}', '')
    first = source.index('    // Keep separate host buffers for every time step.', source.index('fn pt_loss_host('))
    last = source.index('    let weights=0;', first)
    source = source[:first] + '    let action_bytes=pt_batch*pt_action_width*4;let t=0;\n' + source[last:]
    first = source.index('    vp_require(f64_is_finite(loss),"nonfinite training loss");if training {', source.index('fn pt_loss_host('))
    last = source.index('\nfn pt_order_file(', first)
    source = source[:first] + '    vp_require(f64_is_finite(loss),"nonfinite training loss");return loss;\n}\n' + source[last:]
    return source


class TrainerHostLossTest(unittest.TestCase):
    def test_real_batch_and_loss_masks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            shutil.copytree(ROOT / 'flex', root / 'flex', symlinks=True)
            (root / 'build').symlink_to(ROOT / 'build', target_is_directory=True)
            source = root / 'flex/control/train.flex'
            source.write_text(host_source(source.read_text()) +
                              '\nfn pt_loss(training,rate) { return pt_loss_host(training,rate); }\n' +
                              (HERE / 'probe.flex').read_text())
            binary = root / 'probe'
            built = subprocess.run([str(ROOT / 'build/flex/control/compiler'), str(source), '-o', str(binary)],
                                   cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([str(binary)], cwd=ROOT, check=True, capture_output=True, text=True, timeout=15)
            self.assertIn('Native trainer host mask and loss-seed probe passed.', result.stdout)


if __name__ == '__main__':
    unittest.main()
