#!/usr/bin/env python3
"""Exercise only synthetic, snapshot-only native bootstrap binaries."""
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('positive_bootstrap_build', HERE / 'build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='puppy-positive-bootstrap-')
        self.root = Path(self.temporary.name)
        self.catalog = self.root / 'catalog'
        self.catalog.mkdir()
        rows = []
        for index, layout, fit in ((0, 17, True), (1, 125, False)):
            scene = self.catalog / str(index)
            scene.mkdir()
            data = {'case.json': f'case {index}'.encode(),
                    'environment.bin': f'environment {index}'.encode(),
                    'layout.json': json.dumps({'layoutId': layout, 'fit': fit}).encode()}
            for name, value in data.items():
                (scene / name).write_bytes(value)
            rows.append({'index': index, 'seed': 70 + index, 'role': 'fit' if fit else 'validation',
                         'caseSHA256': digest(data['case.json']),
                         'environmentSHA256': digest(data['environment.bin']),
                         'layoutSHA256': digest(data['layout.json'])})
        self.allowlist = {'schema': 'puppybot.positive-bootstrap.v1', 'status': 'synthetic_only',
                          'episodes': 2, 'validation': 1, 'seed': 70, 'rows': rows}
        self.counter = 0
        self.path, self.binary = self.compile(self.allowlist)

    def tearDown(self):
        self.temporary.cleanup()

    def compile(self, value):
        self.counter += 1
        policy = self.root / f'allowlist-{self.counter}.json'
        policy.write_text(json.dumps(value, sort_keys=True))
        build = self.root / f'build-{self.counter}'
        receipt = builder.build(policy, build)
        self.assertEqual(receipt['allowlistSHA256'], digest(policy.read_bytes()))
        self.assertEqual(receipt['binarySHA256'], digest((build / 'snapshot').read_bytes()))
        return policy, build / 'snapshot'

    def run_snapshot(self, policy=None, binary=None, suffix='output'):
        output = self.root / suffix
        result = subprocess.run([str(binary or self.binary), 'snapshot', str(policy or self.path),
                                 str(self.catalog), str(output)], cwd=ROOT, capture_output=True, text=True)
        return result, output

    def test_approved_snapshots_and_compiled_identity(self):
        result, output = self.run_snapshot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((output / 'allowlist.json').read_bytes(), self.path.read_bytes())
        for index in (0, 1):
            for name in ('case.json', 'environment.bin', 'layout.json'):
                self.assertEqual((output / 'scenes' / str(index) / name).read_bytes(),
                                 (self.catalog / str(index) / name).read_bytes())
        (self.catalog / '0/case.json').write_bytes(b'later mutation')
        self.assertEqual((output / 'scenes/0/case.json').read_bytes(), b'case 0')

    def test_forged_policy_or_changed_missing_scene_rejected_before_output(self):
        forged = self.root / 'forged.json'
        forged.write_text(json.dumps(dict(self.allowlist, seed=71)))
        result, output = self.run_snapshot(policy=forged, suffix='forged-out')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('allowlist identity differs', result.stderr)
        self.assertFalse(output.exists())
        (self.catalog / '1/environment.bin').write_bytes(b'changed')
        result, output = self.run_snapshot(suffix='changed-out')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('scene bytes differ', result.stderr)
        self.assertFalse(output.exists())
        (self.catalog / '1/environment.bin').unlink()
        result, output = self.run_snapshot(suffix='missing-out')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_wrong_split_reserved_layout_and_reserved_seed_rejected(self):
        mutations = [({'layoutId': 226, 'fit': True}, 70),
                     ({'layoutId': 290, 'fit': True}, 70),
                     ({'layoutId': 17, 'fit': False}, 70),
                     ({'layoutId': 17, 'fit': True, 'reservedHeldOut': True}, 70),
                     ({'layoutId': 17, 'fit': True}, 1700000099)]
        for index, (layout, seed) in enumerate(mutations):
            data = json.dumps(layout).encode()
            (self.catalog / '0/layout.json').write_bytes(data)
            value = copy.deepcopy(self.allowlist)
            value['seed'] = seed
            for row in value['rows']:
                row['seed'] = seed + row['index']
            value['rows'][0]['layoutSHA256'] = digest(data)
            path, binary = self.compile(value)
            result, output = self.run_snapshot(path, binary, f'reserved-{index}')
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertFalse(output.exists())

    def test_duplicate_scene_content_is_rejected(self):
        value = copy.deepcopy(self.allowlist)
        data = (self.catalog / '0/environment.bin').read_bytes()
        (self.catalog / '1/environment.bin').write_bytes(data)
        value['rows'][1]['environmentSHA256'] = digest(data)
        path, binary = self.compile(value)
        result, output = self.run_snapshot(path, binary, 'duplicate')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate bootstrap scene bytes', result.stderr)
        self.assertFalse(output.exists())

    def test_no_collector_training_or_extra_arguments(self):
        commands = [
            ['collect', '--scene', str(self.catalog), '--output', str(self.root / 'collect')],
            ['collect', '--fetch', '--scene-catalog', str(self.catalog), '--output', str(self.root / 'catalog-out')],
            ['correct', '--output', str(self.root / 'correct')],
            ['run', '--output', str(self.root / 'run')],
            ['train', '--data', str(self.root / 'opaque.bin'), '--output', str(self.root / 'train')],
            ['pack-data', '--data', str(self.root / 'opaque.bin'), '--output', str(self.root / 'pack')],
            ['snapshot', str(self.path), str(self.catalog), str(self.root / 'extra'), '--policy', 'fake'],
        ]
        for command in commands:
            result = subprocess.run([str(self.binary), *command], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('bootstrap permits only snapshot', result.stderr)
        for name in ('collect', 'catalog-out', 'correct', 'run', 'train', 'pack', 'extra'):
            self.assertFalse((self.root / name).exists())

    def test_unknown_rows_and_caller_replacement_do_not_override_compiled_digest(self):
        value = copy.deepcopy(self.allowlist)
        value['rows'][0]['caseSHA256'] = digest(b'unknown')
        forged = self.root / 'unknown.json'
        forged.write_text(json.dumps(value, sort_keys=True))
        result, output = self.run_snapshot(forged, suffix='unknown')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_private_build_recompile_and_alias_tampering(self):
        build = self.binary.parent
        self.assertEqual(builder.verify(self.path, build, recompile=True)['binarySHA256'],
                         digest(self.binary.read_bytes()))
        external = self.root / 'external-hardlink'
        os.link(self.binary, external)
        with self.assertRaisesRegex(ValueError, 'single-link'):
            builder.verify(self.path, build)
        external.unlink()
        saved = self.binary.read_bytes()
        self.binary.unlink()
        target = self.root / 'target'
        target.write_bytes(saved)
        self.binary.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'single-link'):
            builder.verify(self.path, build)

    def test_existing_output_is_preserved(self):
        output = self.root / 'existing'
        output.mkdir()
        (output / 'sentinel').write_text('keep')
        result = subprocess.run([str(self.binary), 'snapshot', str(self.path), str(self.catalog), str(output)],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((output / 'sentinel').read_text(), 'keep')
        self.assertEqual(sorted(path.name for path in output.iterdir()), ['sentinel'])


if __name__ == '__main__':
    unittest.main()
