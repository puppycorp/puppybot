#!/usr/bin/env python3
"""CPU-only native guarded collector integration tests using synthetic files."""
import hashlib
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


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


policy = load('native_guard_policy', HERE / 'policy.py')
transform = load('native_guard_transform', HERE / 'transform.py')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def manifest(kind):
    rows = []
    for level in range(1, 6):
        for index in range(32):
            layout = ((290 + index if level <= 3 else 291 + 2 * index) if kind == 'selection'
                      else (226 + index if level <= 3 else 227 + 2 * index))
            row = {'level': level, 'index': index, 'layoutId': layout,
                   'seed': (1800000000 if kind == 'selection' else 1700000000) + 100 * level + index,
                   'scene': f'generated/{layout}/{index % 16}',
                   'caseSHA256': digest(f'{kind}-case-{layout}-{index % 16}'.encode()),
                   'environmentSHA256': digest(f'{kind}-env-{layout}'.encode())}
            if kind == 'selection':
                row['layoutSHA256'] = digest(f'layout-{layout}'.encode())
                row['startPose'] = [layout, 0, 0]
            rows.append(row)
    out = {'status': 'selection_not_evaluated' if kind == 'selection' else 'reserved_not_evaluated',
           'task': 'virtual-fetch', 'gamesPerLevel': 32, 'rows': rows}
    if kind == 'selection':
        out.update(generatorSourceSHA256='a' * 64, generatorSHA256='b' * 64)
    return out


class NativeIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='puppy-native-guard-')
        cls.root = Path(cls.tmp.name)
        cls.source = cls.root / 'flex'
        shutil.copytree(ROOT / 'flex', cls.source)
        control = cls.source / 'control'
        (control / 'scene-guard.flex').write_text((HERE / 'scene-guard.flex').read_text())
        (control / 'main.flex').write_text(transform.main_source((control / 'main.flex').read_text()))
        (control / 'chase.flex').write_text(transform.chase_source((control / 'chase.flex').read_text()))
        cls.binary = cls.root / 'control'
        result = subprocess.run([str(COMPILER), str(control / 'main.flex'), '-o', str(cls.binary)],
                                cwd=ROOT, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        consumption = cls.root / 'consume.flex'
        consumption.write_text(f'''import "{control / 'chase.flex'}";
fn main(argc,argv) {{
    vc_init(argc,argv);vc_require(argc==9,"probe needs guard inputs and scene hashes");
    vg_policy=load64(argv+8);vg_expected_sha=load64(argv+16);vg_selection_manifest=load64(argv+24);vg_heldout_manifest=load64(argv+32);
    let catalog=load64(argv+40);let output=load64(argv+48);vc_mkdir(output);vg_prepare(output,catalog,2,1,70);
    vc_write(vc_path(vc_path(catalog,"0"),"case.json"),"changed",7);
    let first=vc_path(vx_scene(0),"case.json");let second=vc_path(vx_scene(1),"case.json");
    vc_require(pl_equal(vc_file_sha(first),load64(argv+56)) && pl_equal(vc_file_sha(second),load64(argv+64)),"collector did not consume guarded snapshots");
    pl_print(1,"snapshots consumed\\n");return 0;
}}
''')
        cls.consume = cls.root / 'consume'
        result = subprocess.run([str(COMPILER), str(consumption), '-o', str(cls.consume)], cwd=ROOT,
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        probe = cls.root / 'probe.flex'
        probe.write_text(f'''import "{control / 'scene-guard.flex'}";
fn main(argc,argv) {{
    vc_init(argc,argv);vc_require(argc==8,"probe needs policy sha selection heldout catalog output seed");
    vg_policy=load64(argv+8);vg_expected_sha=load64(argv+16);vg_selection_manifest=load64(argv+24);vg_heldout_manifest=load64(argv+32);let catalog=load64(argv+40);let output=load64(argv+48);
    let seed_text=load64(argv+56);let seed=pl_integer(seed_text,pl_size(seed_text));vc_require(!pl_bad_number,"invalid seed");
    vc_mkdir(output);vg_prepare(output,catalog,2,1,seed);pl_print(1,"guard accepted\\n");return 0;
}}
''')
        cls.probe = cls.root / 'probe'
        result = subprocess.run([str(COMPILER), str(probe), '-o', str(cls.probe)], cwd=ROOT,
                                capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(dir=self.root)
        self.path = Path(self.case.name)
        self.catalog = self.path / 'catalog'; self.catalog.mkdir()
        self.manifests = {}
        for kind in ('selection', 'heldout'):
            path = self.path / (kind + '.json'); data = json.dumps(manifest(kind)).encode(); path.write_bytes(data)
            self.manifests[kind] = (path, digest(data))
        for index, layout, fit in ((0, 17, True), (1, 126, False)):
            scene = self.catalog / str(index); scene.mkdir()
            (scene / 'case.json').write_bytes(f'case {index}'.encode())
            (scene / 'environment.bin').write_bytes(f'environment {index}'.encode())
            (scene / 'layout.json').write_text(json.dumps({'layoutId': layout, 'fit': fit}))

    def tearDown(self):
        self.case.cleanup()

    def create_policy(self):
        s, sh = self.manifests['selection']; h, hh = self.manifests['heldout']
        value = policy.prepare(s, sh, h, hh, self.catalog, 2, 1, 70)
        path = self.path / 'policy.json'; sha = policy.write_new(path, value)
        return path, sha, value

    def run_probe(self, path, sha, name='out', seed=70):
        return subprocess.run([str(self.probe), str(path), sha, str(self.manifests['selection'][0]),
                               str(self.manifests['heldout'][0]), str(self.catalog), str(self.path / name), str(seed)],
                              cwd=ROOT, capture_output=True, text=True)

    def test_guarded_snapshot_copies_exact_files_and_split(self):
        path, sha, _ = self.create_policy(); result = self.run_probe(path, sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        for index in (0, 1):
            for name in ('case.json', 'environment.bin', 'layout.json'):
                self.assertEqual((self.catalog / str(index) / name).read_bytes(),
                                 (self.path / 'out/guarded-scenes' / str(index) / name).read_bytes())

    def test_actual_scene_resolver_uses_snapshot_after_catalog_changes(self):
        path, sha, _ = self.create_policy()
        expected = [digest((self.catalog / str(i) / 'case.json').read_bytes()) for i in (0, 1)]
        result = subprocess.run([str(self.consume), str(path), sha, str(self.manifests['selection'][0]),
                                 str(self.manifests['heldout'][0]), str(self.catalog), str(self.path / 'consumed'),
                                 *expected], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.catalog / '0/case.json').read_bytes(), b'changed')
        self.assertEqual((self.path / 'consumed/guarded-scenes/0/case.json').read_bytes(), b'case 0')

    def test_bad_digest_and_changed_source_fail_closed(self):
        path, sha, _ = self.create_policy()
        self.assertNotEqual(self.run_probe(path, '0' * 64, 'bad-hash').returncode, 0)
        (self.catalog / '1/case.json').write_bytes(b'changed')
        self.assertNotEqual(self.run_probe(path, sha, 'changed').returncode, 0)

    def test_stripped_marker_reserved_content_is_rejected_by_native(self):
        path, _, value = self.create_policy()
        blocked = b'heldout env 226'; (self.catalog / '0/environment.bin').write_bytes(blocked)
        value['rows'][0]['environmentSHA256'] = digest(blocked)
        value['denyEnvironments'].append(digest(blocked))
        path.unlink(); sha = policy.write_new(path, value)
        result = self.run_probe(path, sha)
        self.assertNotEqual(result.returncode, 0); self.assertIn('reserved scene bytes', result.stderr)

    def test_missing_or_empty_reserved_lists_fail_closed(self):
        path, _, value = self.create_policy()
        for index, replacement in enumerate((None, [])):
            changed = dict(value)
            if replacement is None:
                del changed['denyCases']
            else:
                changed['denyEnvironments'] = replacement
            path.unlink(); sha = policy.write_new(path, changed)
            result = self.run_probe(path, sha, f'missing-{index}')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('reserved hash lists required', result.stderr)

    def test_forged_policy_omitting_manifest_hash_fails_closed(self):
        path, _, value = self.create_policy()
        blocked = b'heldout-env-226'; reserved = digest(blocked)
        self.assertIn(reserved, value['denyEnvironments'])
        (self.catalog / '0/environment.bin').write_bytes(blocked)
        value['rows'][0]['environmentSHA256'] = reserved
        value['denyEnvironments'].remove(reserved)
        path.unlink(); sha = policy.write_new(path, value)
        result = self.run_probe(path, sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('guard policy omits reserved scene hash', result.stderr)

    def test_changed_reservation_manifest_fails_closed(self):
        path, sha, _ = self.create_policy()
        self.manifests['heldout'][0].write_bytes(b'{}')
        result = self.run_probe(path, sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('reservation manifest digest differs', result.stderr)

    def test_reserved_seed_range_rejected_by_preparer_and_native(self):
        path, _, value = self.create_policy()
        s, sh = self.manifests['selection']; h, hh = self.manifests['heldout']
        for index, seed in enumerate((1700000100, 1700000130, 1700000531,
                                      1800000100, 1800000130, 1800000531, 1800000099)):
            with self.assertRaisesRegex(ValueError, 'seed overlaps'):
                policy.prepare(s, sh, h, hh, self.catalog, 2, 1, seed)
            changed = dict(value); changed['seed'] = seed
            changed['rows'] = [dict(row, seed=seed + i) for i, row in enumerate(value['rows'])]
            path.unlink(); sha = policy.write_new(path, changed)
            result = self.run_probe(path, sha, f'reserved-{index}', seed)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('seed overlaps a reserved game', result.stderr)
        with self.assertRaisesRegex(ValueError, 'invalid guard split or seed'):
            policy.prepare(s, sh, h, hh, self.catalog, 2, 1, 2147483647)

    def test_reserved_role_and_split_are_rejected_by_native(self):
        path, _, value = self.create_policy()
        for metadata in ({'layoutId': 226, 'fit': True}, {'layoutId': 17, 'fit': True, 'selectionOnly': True},
                         {'layoutId': 17, 'fit': False}):
            data = json.dumps(metadata).encode(); (self.catalog / '0/layout.json').write_bytes(data)
            value['rows'][0]['layoutSHA256'] = digest(data); path.unlink(); sha = policy.write_new(path, value)
            result = self.run_probe(path, sha, f'out-{len(list(self.path.glob("out-*")))}')
            self.assertNotEqual(result.returncode, 0)

    def test_private_binary_refuses_unsupported_paths_before_io(self):
        for command in ('train', 'correct', 'run', 'pack-data'):
            result = subprocess.run([str(self.binary), command, '--output', str(self.path / command)],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('protected binary only permits guarded', result.stderr)
            self.assertFalse((self.path / command).exists())

    def test_unprotected_collection_refused_before_output(self):
        result = subprocess.run([str(self.binary), 'collect', '--fetch', '--scene-catalog', str(self.catalog),
                                 '--output', str(self.path / 'noguard')], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('protected binary only permits guarded', result.stderr)
        self.assertFalse((self.path / 'noguard').exists())

    def test_native_collector_rejects_changed_catalog_before_dataset_or_policy(self):
        path, sha, _ = self.create_policy()
        (self.catalog / '1/case.json').write_bytes(b'drift')
        out = self.path / 'collection'
        result = subprocess.run([str(self.binary), 'collect', '--fetch', '--scene-catalog', str(self.catalog),
                                 '--episodes', '2', '--validation', '1', '--seed', '70', '--output', str(out),
                                 '--scene-guard-policy', str(path), '--scene-guard-sha256', sha,
                                 '--scene-guard-selection', str(self.manifests['selection'][0]),
                                 '--scene-guard-heldout', str(self.manifests['heldout'][0])],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('scene bytes differ', result.stderr)
        self.assertFalse((out / 'data.partial.bin').exists())
        self.assertFalse((out / 'policy.log').exists())


if __name__ == '__main__':
    unittest.main()
