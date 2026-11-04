#!/usr/bin/env python3
"""CPU-only synthetic guard and native generator role tests; no scenes run."""
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMPILER = ROOT / 'build/flex/control/compiler'
GENERATOR = ROOT / 'datasets/visual-control/expanded-rooms-v1/generate-diverse.flex'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load('selection_role_guard', HERE / 'guard.py')
patcher = load('selection_role_transform', HERE / 'transform.py')
design = load('selection_role_design', HERE / 'design.py')
preparation = load('selection_role_preparation', HERE / 'prepare.py')


def sha(data):
    return hashlib.sha256(data).hexdigest()


class RoleGuardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.selection = self.root / 'selection.json'; self.heldout = self.root / 'heldout.json'
        self.target = self.root / 'target'; self.target.mkdir()
        self.layout = {'generator': 'diverse-v1', 'layoutId': 290, 'fit': False,
                       'selectionOnly': True, 'startPose': [2.9, 0, 0], 'obstacles': [[1, 2, 3, 4]]}
        self.write_scene(self.target, self.layout, b'selection case 290 0', b'selection env 290')
        selection = self.manifest('selection'); reserved = self.manifest('heldout')
        self.selection.write_text(json.dumps(selection)); self.heldout.write_text(json.dumps(reserved))
        self.selection_sha = sha(self.selection.read_bytes()); self.heldout_sha = sha(self.heldout.read_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def write_scene(self, root, layout, case, env):
        (root / 'layout.json').write_text(json.dumps(layout))
        (root / 'case.json').write_bytes(case); (root / 'environment.bin').write_bytes(env)

    def manifest(self, role):
        rows = []
        for level in range(1, 6):
            for index in range(32):
                layout = (290 + index if level <= 3 else 291 + 2 * index) if role == 'selection' else (
                    226 + index if level <= 3 else 227 + 2 * index)
                seed = (1800000000 if role == 'selection' else 1700000000) + level * 100 + index
                variant = index % 16
                row = {'level': level, 'index': index, 'layoutId': layout, 'seed': seed,
                       'scene': f'generated/{layout}/{variant}',
                       'caseSHA256': sha(f'{role} case {layout} {variant}'.encode()),
                       'environmentSHA256': sha(f'{role} env {layout}'.encode())}
                if role == 'selection':
                    metadata = {'generator': 'diverse-v1', 'layoutId': layout, 'fit': False,
                                'selectionOnly': True, 'startPose': [layout / 100, 0, 0], 'obstacles': [[1, 2, 3, 4]]}
                    row['layoutSHA256'] = sha(json.dumps(metadata).encode())
                    row['startPose'] = metadata['startPose']
                rows.append(row)
        result = {'status': 'selection_not_evaluated' if role == 'selection' else 'reserved_not_evaluated',
                  'task': 'virtual-fetch', 'gamesPerLevel': 32, 'rows': rows}
        if role == 'selection':
            result.update(generatorSourceSHA256='0' * 64, generatorSHA256='1' * 64)
        return result

    def make_guard(self):
        return guard.SceneGuard(self.selection, self.selection_sha, self.heldout, self.heldout_sha)

    def test_selection_requires_exact_role_mapping_seed_and_bytes(self):
        g = self.make_guard()
        files = g.snapshot(self.target, 'selection', level=1, index=0, seed=1800000100)
        self.assertEqual(files['case.json'], b'selection case 290 0')
        for kwargs in ({'level': 1, 'index': 0, 'seed': 1800000101},
                       {'level': 1, 'index': 1, 'seed': 1800000100}, {}):
            with self.assertRaises(ValueError):
                g.snapshot(self.target, 'selection', **kwargs)
        (self.target / 'case.json').write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            g.snapshot(self.target, 'selection', level=1, index=0, seed=1800000100)

    def test_fit_and_validation_reject_selection_even_if_metadata_stripped(self):
        g = self.make_guard()
        for purpose in ('fit', 'validation'):
            with self.assertRaises(ValueError):
                g.snapshot(self.target, purpose)
        # Forge an older layout role and ID; original selected environment
        # bytes must still prevent ingestion even when the case also changes.
        self.write_scene(self.target, {'layoutId': 17, 'fit': True}, b'other case', b'selection env 290')
        with self.assertRaises(ValueError):
            g.snapshot(self.target, 'fit')
        self.write_scene(self.target, {'layoutId': 17, 'fit': False}, b'selection case 290 0', b'other env')
        with self.assertRaises(ValueError):
            g.snapshot(self.target, 'validation')

    def test_legitimate_fit_validation_and_heldout_rejected(self):
        g = self.make_guard()
        self.write_scene(self.target, {'layoutId': 17, 'fit': True}, b'fit case', b'fit env')
        self.assertEqual(g.snapshot(self.target, 'fit')['case.json'], b'fit case')
        with self.assertRaises(ValueError):
            g.snapshot(self.target, 'validation')
        self.write_scene(self.target, {'layoutId': 126, 'fit': False}, b'val case', b'val env')
        self.assertEqual(g.snapshot(self.target, 'validation')['case.json'], b'val case')
        for metadata, case, env in (({'layoutId': 226, 'fit': False}, b'x', b'y'),
                                    ({'layoutId': 126, 'fit': False, 'reservedHeldOut': True}, b'x', b'y'),
                                    ({'layoutId': 126, 'fit': False}, b'heldout case 226 0', b'y'),
                                    ({'layoutId': 126, 'fit': False}, b'x', b'heldout env 226')):
            self.write_scene(self.target, metadata, case, env)
            with self.assertRaises(ValueError):
                g.snapshot(self.target, 'validation')

    def test_manifest_identity_and_duplicate_are_fail_closed(self):
        with self.assertRaises(ValueError):
            guard.SceneGuard(self.selection, '0' * 64, self.heldout, self.heldout_sha)
        data = json.loads(self.selection.read_text()); data['rows'][1] = data['rows'][0]
        self.selection.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            guard.SceneGuard(self.selection, sha(self.selection.read_bytes()), self.heldout, self.heldout_sha)

    def test_duplicate_environment_or_start_pose_and_unpinned_generator_rejected(self):
        for field in ('environmentSHA256', 'startPose'):
            data = self.manifest('selection')
            data['rows'][1][field] = data['rows'][0][field]
            self.selection.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'duplicate environment or start pose'):
                guard.SceneGuard(self.selection, sha(self.selection.read_bytes()), self.heldout, self.heldout_sha)
        data = self.manifest('selection'); del data['generatorSHA256']
        self.selection.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'generator identity'):
            guard.SceneGuard(self.selection, sha(self.selection.read_bytes()), self.heldout, self.heldout_sha)
        data = self.manifest('selection'); data['rows'][0]['seed'] += 1
        self.selection.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            guard.SceneGuard(self.selection, sha(self.selection.read_bytes()), self.heldout, self.heldout_sha)

    def test_symlink_snapshot_is_not_reopened_after_retarget(self):
        link = self.root / 'catalog'; link.symlink_to(self.target, target_is_directory=True)
        g = self.make_guard()
        snapshot = g.snapshot(link, 'selection', level=1, index=0, seed=1800000100)
        other = self.root / 'other'; other.mkdir()
        self.write_scene(other, {'layoutId': 17, 'fit': True}, b'other', b'other')
        link.unlink(); link.symlink_to(other, target_is_directory=True)
        self.assertEqual(snapshot['case.json'], b'selection case 290 0')
        with self.assertRaises(ValueError):
            g.snapshot(link, 'selection', level=1, index=0, seed=1800000100)


class GeneratorTransformTest(unittest.TestCase):
    def test_native_role_boundaries_and_synthetic_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = patcher.transform(GENERATOR.read_text())
            source = source.replace('import "../../../flex/control/scene.flex";',
                                    f'import "{ROOT / "flex/control/scene.flex"}";')
            source = source.replace('fn main(argc,argv) {', 'fn original_generator_main(argc,argv) {')
            source += '''
fn main(argc,argv) {
    vc_init(argc,argv);
    vc_require(dv_role_allowed("selection",290,354,0,0),"selection rejected");
    vc_require(!dv_role_allowed("selection",289,290,0,0),"selection includes heldout");
    vc_require(!dv_role_allowed("selection",353,355,0,0),"selection upper bound");
    vc_require(!dv_role_allowed("selection",290,291,1,0),"wide selection accepted");
    vc_require(!dv_role_allowed("selection",290,291,0,1),"empty-obstacle selection accepted");
    vc_require(dv_role_allowed("held-out",226,290,0,0),"heldout role changed");
    vc_require(!dv_role_allowed("held-out",226,291,0,0),"heldout overlaps selection");
    vc_require(!dv_role_allowed("fit",290,291,0,0),"fit accepts selection");
    vc_require(!dv_role_allowed("validation",290,291,0,0),"validation accepts selection");
    vc_require(!dv_role_allowed("selection",290,290,0,0),"empty selection accepted");
    dv_params=alloc(15*8);pb_zero(dv_params,15*8);dv_selection=1;dv_held_out=0;
    dv_layout(load64(argv+8),290,0);return 0;
}
'''
            path = root / 'probe.flex'; path.write_text(source); binary = root / 'probe'
            build = subprocess.run([str(COMPILER), str(path), '-o', str(binary)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            metadata = root / 'synthetic-layout.json'
            run = subprocess.run([str(binary), str(metadata)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            observed = json.loads(metadata.read_text())
            self.assertEqual(observed['layoutId'], 290)
            self.assertIs(observed['fit'], False)
            self.assertIs(observed['selectionOnly'], True)
            self.assertNotIn('reservedHeldOut', observed)

    def test_transform_rejects_unexpected_source(self):
        with self.assertRaises(ValueError):
            patcher.transform('fn main() {}')


class DesignTest(unittest.TestCase):
    def test_level_seed_layout_and_reserved_boundary(self):
        rows = design.rows()
        self.assertEqual(len(rows), 160)
        self.assertEqual(len({row['seed'] for row in rows}), 160)
        for row in rows:
            self.assertTrue(290 <= row['layoutId'] <= 353)
            self.assertEqual(row['seed'], 1800000000 + 100 * row['level'] + row['index'])
            if row['level'] >= 4:
                self.assertEqual(row['layoutId'] % 2, 1)
        self.assertTrue({row['seed'] for row in rows}.isdisjoint(
            {1700000000 + 100 * level + index for level in range(1, 6) for index in range(32)}))

    def test_geometry_ignores_layout_id_and_sorts_rectangles(self):
        first = {'layoutId': 10, 'rooms': [[-2, -1, 0, 1], [0, -1, 2, 1]],
                 'door': [0, 0, 0.5], 'obstacles': [[-1, 0, .2, .3], [1, 0, .2, .3]]}
        renamed = {'layoutId': 300, 'rooms': list(reversed(first['rooms'])),
                   'door': [0.0, -0.0, .5], 'obstacles': list(reversed(first['obstacles']))}
        self.assertEqual(design.geometry(first), design.geometry(renamed))
        with self.assertRaisesRegex(ValueError, 'geometry'):
            design.compare_history([42], [first], [renamed])
        changed = dict(renamed, door=[0, .01, .5])
        self.assertEqual(design.compare_history([42], [first], [changed])['status'],
                         'supplied_history_no_exact_overlap')
        with self.assertRaisesRegex(ValueError, 'seeds'):
            design.compare_history([1800000100], [first], [changed])
        with self.assertRaises(ValueError):
            design.geometry(dict(first, door=[0, float('nan'), .5]))


class PreparationTest(unittest.TestCase):
    write_scene = RoleGuardTest.write_scene
    manifest = RoleGuardTest.manifest
    tearDown = RoleGuardTest.tearDown

    def setUp(self):
        RoleGuardTest.setUp(self)
        self.generator_source = self.root / 'generator.flex'
        self.generator_source.write_text(patcher.transform(GENERATOR.read_text()))
        self.generator_binary = self.root / 'generator-binary'
        self.generator_binary.write_bytes(b'synthetic binary, never executed')
        self.prior = {'rooms': [[-2, -1, 2, 1]], 'door': None, 'obstacles': []}
        for row in design.rows():
            layout, variant = row['layoutId'], row['variant']
            scene = self.root / 'generated' / str(layout) / str(variant)
            if scene.exists():
                continue
            scene.mkdir(parents=True)
            rooms = [[-layout, -1, layout, 1]]
            door = None
            if layout % 2:
                rooms = [[-layout, -1, 0, 1], [0, -1, layout, 1]]; door = [0, 0, .8]
            metadata = {'generator': 'diverse-v1', 'layoutId': layout, 'fit': False,
                        'selectionOnly': True, 'startPose': [layout / 100, 0, 0],
                        'rooms': rooms, 'door': door, 'obstacles': [[1, 2, 3, 4]]}
            case = json.dumps({'synthetic': True, 'layout': layout, 'variant': variant}).encode()
            environment = b'PBENV001' + str(layout).encode().ljust(248, b'\0')
            self.write_scene(scene, metadata, case, environment)

    def prepare(self, seeds=(42,), prior=None, prior_cases=None, prior_environments=None):
        return preparation.prepare(self.root, self.generator_source, self.generator_binary,
                                   self.heldout, self.heldout_sha, list(seeds), [prior or self.prior],
                                   [sha(b'prior case')] if prior_cases is None else prior_cases,
                                   [sha(b'prior environment')] if prior_environments is None else prior_environments)

    def test_prepare_requires_unique_environments_poses_and_metadata_geometry(self):
        plan = self.prepare()
        self.assertEqual(len(plan['rows']), 160)
        self.assertEqual(plan['generatorSourceSHA256'], sha(self.generator_source.read_bytes()))
        self.assertEqual(plan['generatorSHA256'], sha(self.generator_binary.read_bytes()))
        self.assertEqual(plan['history']['priorCaseInventorySHA256'],
                         sha(json.dumps([sha(b'prior case')], separators=(',', ':')).encode()))
        self.assertEqual(plan['history']['priorEnvironmentInventorySHA256'],
                         sha(json.dumps([sha(b'prior environment')], separators=(',', ':')).encode()))
        self.selection.write_text(json.dumps(plan))
        validated = guard.SceneGuard(self.selection, sha(self.selection.read_bytes()), self.heldout, self.heldout_sha)
        validated.snapshot(self.root / 'generated/290/0', 'selection', level=1, index=0, seed=1800000100)
        scene = self.root / 'generated/291/1'
        (scene / 'environment.bin').write_bytes((self.root / 'generated/290/0/environment.bin').read_bytes())
        with self.assertRaisesRegex(ValueError, 'duplicate environment'):
            self.prepare()

    def test_prepare_rejects_duplicate_poses_and_wrong_source(self):
        scene = self.root / 'generated/291/1/layout.json'
        metadata = json.loads(scene.read_text()); metadata['startPose'] = [2.9, 0, 0]
        scene.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, 'duplicate environment, start pose or exact metadata geometry'):
            self.prepare()
        self.generator_source.write_text('not the reviewed transform')
        with self.assertRaisesRegex(ValueError, 'not the reviewed transform'):
            self.prepare()

    def test_prepare_rejects_duplicate_metadata_geometry_and_prior_overlap(self):
        scene = self.root / 'generated/292/2/layout.json'
        metadata = json.loads(scene.read_text()); metadata['rooms'] = [[-290, -1, 290, 1]]
        scene.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, 'duplicate environment, start pose or exact metadata geometry'):
            self.prepare()
        metadata['rooms'] = [[-292, -1, 292, 1]]; scene.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, 'seeds'):
            self.prepare(seeds=[1800000100])

    def test_prepare_rejects_scene_changed_during_scan(self):
        original = preparation.design.compare_history
        def mutate(*args):
            value = original(*args)
            (self.root / 'generated/290/0/case.json').write_text('{"changed":true}')
            return value
        with mock.patch.object(preparation.design, 'compare_history', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'changed during preparation'):
                self.prepare()

    def test_prepare_rejects_prior_case_or_environment_content_overlap(self):
        scene = self.root / 'generated/290/0'
        case = sha((scene / 'case.json').read_bytes())
        environment = sha((scene / 'environment.bin').read_bytes())
        with self.assertRaisesRegex(ValueError, 'overlap supplied prior history'):
            self.prepare(prior_cases=[case])
        with self.assertRaisesRegex(ValueError, 'overlap supplied prior history'):
            self.prepare(prior_environments=[environment])
        for invalid in ([], ['bad'], '0' * 64):
            with self.assertRaisesRegex(ValueError, 'inventories required'):
                self.prepare(prior_cases=invalid)


if __name__ == '__main__':
    unittest.main()
