#!/usr/bin/env python3
"""CPU-only checks for pilot command matching and non-destructive preflight."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('pilot', ROOT / 'flex/tests/run-attested-pilot.py')
pilot = importlib.util.module_from_spec(spec); spec.loader.exec_module(pilot)


class PilotRunnerTest(unittest.TestCase):
    def test_paired_commands_match_other_than_binary_and_output(self):
        catalog = Path('/tmp/catalog')
        a = pilot.command(Path('/tmp/original'), catalog, Path('/tmp/a'))
        b = pilot.command(Path('/tmp/instrumented'), catalog, Path('/tmp/b'))
        self.assertNotIn('--lean', a)
        self.assertEqual(a[1:a.index('--output') + 1], b[1:b.index('--output') + 1])
        self.assertEqual(a[a.index('--output') + 2:], b[b.index('--output') + 2:])
        self.assertEqual(a[a.index('--seed') + 1], '7800001')
        self.assertEqual(a[a.index('--horizon') + 1], '300')

    def test_mutated_input_and_capacity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'input'; p.write_text('before'); pins = {str(p): pilot.sha(p)}
            pilot.verify_pins(pins); p.write_text('after')
            with self.assertRaises(ValueError): pilot.verify_pins(pins)
            usage = type('Usage', (), {'free': 10})()
            with mock.patch.object(pilot.shutil, 'disk_usage', return_value=usage):
                pilot.require_space(Path(tmp), 10)
                with self.assertRaises(RuntimeError): pilot.require_space(Path(tmp), 11)

    def test_existing_output_fails_before_external_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / 'out'; output.mkdir(); marker = output / 'keep'; marker.write_text('keep')
            with mock.patch.object(pilot, 'PITCH', root), mock.patch.object(pilot, 'OUTPUT', output), \
                    mock.patch.object(pilot.package, 'verify') as verify, mock.patch.object(pilot.prepare, 'prepare') as build:
                with self.assertRaises(ValueError): pilot.main()
            verify.assert_not_called(); build.assert_not_called(); self.assertEqual(marker.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
