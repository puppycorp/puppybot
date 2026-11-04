#!/usr/bin/env python3
"""Scratch-only tests for full-overlay resource evidence."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
path = ROOT / 'datasets/visual-control/chase-v1/levels/prepare-heading-overlays.py'
spec = importlib.util.spec_from_file_location('overlay_resources', path)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


class ResourcesTest(unittest.TestCase):
    def test_real_scratch_reflink_and_source_maps(self):
        with tempfile.TemporaryDirectory(prefix='.resource-fixture-', dir=P) as tmp:
            root = Path(tmp); base = root / 'base'; base.mkdir(); target = root / 'target'
            for name in ('data.bin', 'map.bin'):
                with (base / name).open('wb') as stream:
                    stream.write(os.urandom(1024 * 1024)); stream.flush(); os.fsync(stream.fileno())
            before = m.source_maps(base)
            def create():
                target.mkdir()
                for name in ('data.bin', 'map.bin'):
                    m.overlay.clone(base / name, target / name, m.overlay.signature(base / name))
                return {'status': 'fixture'}
            result, evidence = m.measured_overlay(base, target, before, create, 0)
            self.assertEqual(result, {'status': 'fixture'})
            self.assertEqual(evidence['sourcePhysicalMapBefore'], before)
            self.assertEqual(evidence['sourcePhysicalMapAfter'], before)
            self.assertGreater(evidence['targetExtents']['data.bin']['shared'], 0)
            for name in ('data.bin', 'map.bin'):
                self.assertEqual((base / name).read_bytes(), (target / name).read_bytes())

    def test_changed_source_maps_and_missing_sharing_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); base = root / 'base'; base.mkdir(); target = root / 'target'
            source = {'data.bin': [[0, 1, 10, 11]], 'map.bin': [[0, 1, 20, 21]]}
            changed = {'data.bin': [[0, 1, 30, 31]], 'map.bin': [[0, 1, 20, 21]]}
            extents = {'total': 1, 'exclusive': 1, 'shared': 0}
            with mock.patch.object(m, 'source_maps', side_effect=[source, changed]), \
                 mock.patch.object(m, 'extent_numbers', return_value=extents):
                with self.assertRaisesRegex(ValueError, 'changed during overlay'):
                    m.measured_overlay(base, target, source, lambda: target.mkdir(), 0)
            self.assertTrue(target.exists(), 'created partial must be retained')
            with mock.patch.object(m, 'source_maps', return_value=source), \
                 mock.patch.object(m, 'extent_numbers', return_value=extents):
                with self.assertRaisesRegex(ValueError, 'no reported shared extents'):
                    m.measured_overlay(base, target, source, lambda: None, 0)

    def test_floor_and_invalid_extent_output_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = {'data.bin': [[0, 1, 10, 11]], 'map.bin': [[0, 1, 20, 21]]}
            extents = {'total': 1, 'exclusive': 0, 'shared': 1}
            with mock.patch.object(m, 'source_maps', return_value=source), \
                 mock.patch.object(m, 'extent_numbers', return_value=extents), \
                 mock.patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=9)):
                with self.assertRaisesRegex(ValueError, 'disk floor crossed'):
                    m.measured_overlay(root, root / 'output', source, lambda: None, 10)
            bad = SimpleNamespace(stdout='Total Exclusive Set shared Filename\n1 0 2 /x\n')
            with mock.patch.object(m.subprocess, 'run', return_value=bad):
                with self.assertRaises(ValueError): m.extent_numbers(Path('/x'))

    def test_downstream_evidence_missing_tampered_or_relocated_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); maps = {'data.bin': [[0, 1, 10, 11]], 'map.bin': [[0, 1, 20, 21]]}
            extent = {'total': 100, 'exclusive': 90, 'shared': 10}
            row = {'freeBefore': 34 * 1024**3, 'freeAfter': 33 * 1024**3,
                   'sourcePhysicalMapBefore': maps, 'sourcePhysicalMapAfter': maps,
                   'sourceExtentsBefore': {'data.bin': extent, 'map.bin': extent},
                   'sourceExtentsAfter': {'data.bin': extent, 'map.bin': extent},
                   'targetExtents': {'data.bin': extent, 'map.bin': extent}}
            verifier = m.resource
            with mock.patch.object(verifier, 'OUTPUT', root), mock.patch.object(verifier, 'physical_maps', return_value=maps):
                with self.assertRaises(FileNotFoundError): verifier.collect()
                for arm in ('control', 'treatment'): (root / f'resource-{arm}.json').write_text(json.dumps(row))
                evidence, hashes = verifier.collect(); ready = {'resourceEvidence': evidence, 'resourceEvidenceSHA256': hashes}
                verifier.verify_ready(ready)
                path = root / 'resource-control.json'; changed = dict(row, freeAfter=32 * 1024**3)
                path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, 'differs from pair receipt'): verifier.verify_ready(ready)
                path.write_text(json.dumps(row))
                with mock.patch.object(verifier, 'physical_maps', return_value={'data.bin': [], 'map.bin': []}):
                    with self.assertRaisesRegex(ValueError, 'maps or free-space'): verifier.verify_ready(ready)
                path.unlink()
                with self.assertRaises(FileNotFoundError): verifier.verify_ready(ready)


if __name__ == '__main__': unittest.main()
