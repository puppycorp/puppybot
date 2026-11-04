#!/usr/bin/env python3
"""CPU fixture test of the future catalog-aware monitor adapter."""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


adapter = load('catalog_monitor_adapter', HERE / 'adapter.py')
monitor_source = ROOT / 'experiments/l5-steering-hysteresis-v1/monitor.py'


def design(root):
    scenes = Path(root) / 'scenes'; scenes.mkdir()
    tasks = []
    for level in range(1, 6):
        rows = []
        for i in range(32):
            layout = 13 + 2 * (i % 3) if level >= 4 else 12 + i % 6
            scene = scenes / str(layout) / str(i % 16); scene.mkdir(parents=True, exist_ok=True)
            rows.append({'index': i, 'scene': str(scene), 'layout': layout, 'variant': i % 16})
        tasks.append({'name': f'L{level}', 'level': level, 'rows': rows})
    return {'status': 'frozen_before_play', 'design': {'tasks': tasks, 'gamesPerArmPerLevel': 32},
            'files': {str(path): adapter.postrun.digest_regular(path)['sha256']
                      for path in (HERE / 'adapter.py', adapter.POSTRUN)}}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.output = self.root / 'fresh-policy-selection-v3'
        self.monitored = self.root / 'fresh-policy-selection-monitored-v3'
        self.manifest = self.root / 'fresh-policy-selection-plan-v3.json'; self.frozen = design(self.root)
        self.monitor = load('catalog_test_monitor', monitor_source)
        self.monitor.OUTPUT = self.output; self.monitor.MONITOR = self.monitored; self.monitor.MANIFEST = self.manifest

    def freeze_fixture(self):
        adapter.require_fresh(self.output, self.monitored, self.manifest, base_dir=self.root)
        self.manifest.write_text(json.dumps(self.frozen)); self.monitored.mkdir()

    def test_freshness_protects_existing_prior_and_sibling_paths(self):
        adapter.require_fresh(self.output, self.monitored, self.manifest, base_dir=self.root)
        self.output.mkdir()
        with self.assertRaises(FileExistsError):
            adapter.require_fresh(self.output, self.monitored, self.manifest, base_dir=self.root)
        with self.assertRaisesRegex(ValueError, 'direct children'):
            adapter.require_fresh(adapter.PROTECTED[4], self.monitored, self.manifest, base_dir=self.root)
        with self.assertRaisesRegex(ValueError, 'direct children'):
            adapter.require_fresh(self.root / 'parent' / self.output.name, self.monitored, self.manifest, base_dir=self.root)
        with self.assertRaisesRegex(ValueError, 'versions differ'):
            adapter.require_fresh(self.root / 'fresh-policy-selection-v4', self.monitored, self.manifest, base_dir=self.root)
        with self.assertRaisesRegex(ValueError, 'v3-or-later'):
            adapter.require_fresh(self.root / 'fresh-policy-selection-v2', self.monitored, self.manifest, base_dir=self.root)
        redirect = self.root / 'redirect'; redirect.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinked'):
            adapter.require_fresh(redirect / self.output.name, self.monitored, self.manifest, base_dir=self.root)

    def test_requires_implementation_pins_and_expected_paths(self):
        self.freeze_fixture()
        original = self.frozen['files'][str(HERE / 'adapter.py')]
        self.frozen['files'][str(HERE / 'adapter.py')] = 'wrong'
        self.manifest.write_text(json.dumps(self.frozen))
        with self.assertRaisesRegex(ValueError, 'not pinned'):
            adapter.install(self.monitor, self.output, self.monitored, self.manifest, lambda: self.frozen, base_dir=self.root)
        self.frozen['files'][str(HERE / 'adapter.py')] = original
        self.manifest.write_text(json.dumps(self.frozen))
        self.monitor.OUTPUT = self.root / 'wrong'
        with self.assertRaisesRegex(ValueError, 'paths differ'):
            adapter.install(self.monitor, self.output, self.monitored, self.manifest, lambda: self.frozen, base_dir=self.root)

    def test_real_worker_inventory_and_final_check_with_fixture_process(self):
        self.freeze_fixture(); expected = adapter.postrun.expected_catalogs(self.frozen)
        adapter.install(self.monitor, self.output, self.monitored, self.manifest, lambda: self.frozen, base_dir=self.root)
        code = ('import json,pathlib,sys; root=pathlib.Path(sys.argv[1]); root.mkdir();'
                'f=json.loads(sys.argv[2]); e=json.loads(sys.argv[3]);'
                '[(p.parent.mkdir(parents=True,exist_ok=True),p.symlink_to(t,target_is_directory=True)) '
                'for n,t in e.items() for p in [root/n]];'
                '(root/"inputs.json").write_text(json.dumps(f));'
                '(root/"report.json").write_text(json.dumps({"status":"diagnostic_only"}))')
        self.monitor.worker_command = lambda: [sys.executable, '-I', '-c', code, str(self.output),
                                                json.dumps(self.frozen), json.dumps(expected)]
        self.monitor.REGISTER = self.manifest
        self.monitor.verify_saved = lambda frozen: json.loads((self.output / 'report.json').read_text())
        registrar = SimpleNamespace(verify=lambda: self.frozen)
        sample = {'freeBytes': 8 * 1024 ** 3}
        with (mock.patch.object(self.monitor, 'load', return_value=registrar),
              mock.patch.object(self.monitor, 'baseline'), mock.patch.object(self.monitor, 'sample_disk'),
              mock.patch.object(self.monitor, 'verify_logs'), mock.patch.object(self.monitor, 'require_disk'),
              mock.patch.object(self.monitor.telemetry, 'sample', return_value=sample)):
            self.monitor._worker(self.monitored)
            evidence_path = self.monitored / 'evidence.json'
            evidence = json.loads(evidence_path.read_text())
            self.assertEqual(len(evidence['files']['links']), 160)
            digest = self.monitor.base.sha(evidence_path)
            self.assertEqual(self.monitor.final_check(self.monitored, digest), {'status': 'final_inventory_verified'})
            # A changed catalog link between collection and final audit must censor it.
            path = self.output / next(iter(expected)); path.unlink(); path.symlink_to(self.root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'retargeted'):
                self.monitor.final_check(self.monitored, digest)

    def test_fresh_monitor_and_final_subprocesses_reinstall_adapter(self):
        self.freeze_fixture(); expected = adapter.postrun.expected_catalogs(self.frozen)
        command = [sys.executable, '-B', '-I', str(HERE / 'fixture_driver.py')]
        args = [str(self.root), str(self.output), str(self.monitored), str(self.manifest)]
        worker = subprocess.run(command + ['worker'] + args, capture_output=True, text=True, timeout=30)
        self.assertEqual(worker.returncode, 0, worker.stdout + worker.stderr)
        self.assertEqual(json.loads(worker.stdout), {'worker': 'completed', 'adapterInstalled': True})
        final = subprocess.run(command + ['final'] + args, capture_output=True, text=True, timeout=30)
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
        self.assertEqual(json.loads(final.stdout), {'status': 'final_inventory_verified'})
        link = self.output / next(iter(expected)); target = expected[next(iter(expected))]
        link.unlink(); link.symlink_to(self.root, target_is_directory=True)
        retarget = subprocess.run(command + ['final'] + args, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(retarget.returncode, 0); self.assertIn('retargeted', retarget.stderr)
        link.unlink(); link.symlink_to(target, target_is_directory=True)
        (self.output / 'unexpected').symlink_to(self.root, target_is_directory=True)
        extra = subprocess.run(command + ['final'] + args, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(extra.returncode, 0); self.assertIn('unexpected', extra.stderr)


if __name__ == '__main__':
    unittest.main()
