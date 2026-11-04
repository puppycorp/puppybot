#!/usr/bin/env python3
"""CPU-only checks for capture parity and a monitored child abort."""
import hashlib
import importlib.util
import contextlib
import copy
import io
import json
import os
import pathlib
import struct
import sys
import tempfile
import unittest
from unittest import mock


HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('l5_capture_tested', HERE / 'capture.py')
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def test_saved_parity_rejects_changed_action_event_and_actor(self):
        with tempfile.TemporaryDirectory(prefix='puppybot-l5-parity-') as directory:
            root = pathlib.Path(directory)
            original = root / 'original'
            original.mkdir()
            captured = root / 'runs/7/control/7'
            captured.mkdir(parents=True)
            result = {'seed': 7, 'deliveries': 1}
            events = [{'event': 'start'}, {'event': 'delivery'}]
            actor = bytes(21168)
            actor_sha = hashlib.sha256(actor).hexdigest()
            feedback = [0.0] * 7
            sensor = captured / 'sensor'
            sensor.mkdir()
            def state(tick, image, maximum):
                return {'totalSteps': tick, 'case': {'perception': {'image': image}},
                        'localization': {'evaluation': {'positionErrorM': 0.0,
                                                        'maxPositionErrorM': maximum,
                                                        'headingErrorRad': 0.0}}}
            old, rows = [], []
            for i in range(300):
                row = {'step': 505 + i * 10, 'sequence': i, 'action': [0, 1], 'proprio': feedback,
                       'state': state(505 + i * 10, None, 0.0)}
                old.append(row)
                rows.append(dict(row, state=state(row['step'], f"frame-{row['step']}.png", 0.1), actorSHA256=actor_sha))
                (sensor / f"frame-{row['step']}.png").write_bytes(b'\x89PNG\r\n\x1a\n')
                (captured / f"actor-{row['step']}.rgb").write_bytes(actor)
                (captured / f"actor-{row['step']}.feedback").write_bytes(struct.pack('<7f', *feedback))
            (sensor / 'frame-495.png').write_bytes(b'\x89PNG\r\n\x1a\n')
            (captured / 'actor-495.rgb').write_bytes(actor)
            (captured / 'actor-495.feedback').write_bytes(struct.pack('<7f', *feedback))
            initial_captured = state(495, 'frame-495.png', 0.0)
            (captured / 'initial.json').write_text(json.dumps(initial_captured))
            (original / 'initial.json').write_text(json.dumps(state(495, None, 0.0)))
            trace = []
            for tick in range(1, 3496):
                entry = state(tick, None, 0.1 if tick >= 502 else 0.0)
                if tick == 502:
                    entry['localization']['evaluation']['positionErrorM'] = 0.1
                trace.append(entry)
            trace_path = captured / 'trace.jsonl'
            trace_path.write_text(''.join(json.dumps(x) + '\n' for x in trace))
            for directory_path in (original, captured):
                (directory_path / 'result.json').write_text(json.dumps(result))
                (directory_path / 'chase.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in events))
            (original / 'decisions.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in old))
            decisions = captured / 'decisions.jsonl'
            decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
            with mock.patch.object(capture, 'OUTPUT', root):
                self.assertEqual(capture.audit_game(7, 'control', {'run': str(original)})['actions'], 300)
                rows[1]['action'] = [1, 1]
                decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                with self.assertRaisesRegex(ValueError, 'action differs'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                rows[1]['action'] = [0, 1]
                decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                rows[1]['state']['changed'] = True
                decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                with self.assertRaisesRegex(ValueError, 'state differs'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                del rows[1]['state']['changed']
                decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                (captured / 'chase.jsonl').write_text(json.dumps(events[0]) + '\n')
                with self.assertRaisesRegex(ValueError, 'task events differ'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                (captured / 'chase.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in events))
                (captured / 'actor-505.rgb').write_bytes(b'x' * 21168)
                with self.assertRaisesRegex(ValueError, 'actor frame'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                (captured / 'actor-505.rgb').write_bytes(actor)
                (captured / 'actor-505.feedback').write_bytes(struct.pack('<7f', 1.0, *feedback[1:]))
                with self.assertRaisesRegex(ValueError, 'actor frame'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                (captured / 'actor-505.feedback').write_bytes(struct.pack('<7f', *feedback))
                bad_initial = copy.deepcopy(initial_captured)
                bad_initial['extra'] = True
                (captured / 'initial.json').write_text(json.dumps(bad_initial))
                with self.assertRaisesRegex(ValueError, 'state differs'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                (captured / 'initial.json').write_text(json.dumps(initial_captured))
                rows[1]['state']['case']['perception']['image'] = 'frame-123.png'
                decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                with self.assertRaisesRegex(ValueError, 'recording filename'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                rows[1]['state']['case']['perception']['image'] = f"frame-{rows[1]['step']}.png"
                decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                trace_path.write_text(''.join(json.dumps(x) + '\n' for x in trace if x['totalSteps'] != 502))
                with self.assertRaisesRegex(ValueError, 'not contiguous'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                trace_path.write_text(''.join(json.dumps(x) + '\n' for x in trace))
                trace[501]['localization']['evaluation']['maxPositionErrorM'] = 0.2
                trace_path.write_text(''.join(json.dumps(x) + '\n' for x in trace))
                with self.assertRaisesRegex(ValueError, 'trace maximum differs'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                trace[501]['localization']['evaluation']['maxPositionErrorM'] = 0.1
                trace_path.write_text(''.join(json.dumps(x) + '\n' for x in trace))
                rows[1]['state']['localization']['evaluation']['positionErrorM'] = 0.01
                decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                with self.assertRaisesRegex(ValueError, 'state differs'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                rows[1]['state']['localization']['evaluation']['positionErrorM'] = 0.0
                decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                rows[1]['state']['localization']['evaluation']['maxPositionErrorM'] = 0.0
                decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                with self.assertRaisesRegex(ValueError, 'boundary maximum differs'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                rows[1]['state']['localization']['evaluation']['maxPositionErrorM'] = 0.1
                decisions.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                old[1]['state']['localization']['evaluation']['maxPositionErrorM'] = 0.05
                (original / 'decisions.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in old))
                with self.assertRaisesRegex(ValueError, 'lean boundary maximum differs'):
                    capture.audit_game(7, 'control', {'run': str(original)})
                old[1]['state']['localization']['evaluation']['maxPositionErrorM'] = 0.0
                (original / 'decisions.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in old))
                (captured / 'actor-495.rgb').rename(captured / 'actor-496.rgb')
                with self.assertRaises(FileNotFoundError):
                    capture.audit_game(7, 'control', {'run': str(original)})

    def test_outer_subreaper_cleans_escaped_grandchild(self):
        with tempfile.TemporaryDirectory(prefix='puppybot-l5-cleanup-') as directory:
            root = pathlib.Path(directory)
            (root / 'outer-monitor').mkdir()
            pidfile = root / 'grandchild.pid'
            code = ('import subprocess,sys;'
                    'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],start_new_session=True);'
                    'open(sys.argv[1],"w").write(str(p.pid))')
            with (mock.patch.object(capture, 'OUTPUT', root),
                  mock.patch.object(capture, 'baseline'),
                  mock.patch.object(capture, 'sample', return_value={'gpu': {}})):
                status = capture.supervise_monitored([sys.executable, '-c', code, str(pidfile)])
            self.assertTrue(status['remainingWorkersTerminated'])
            self.assertFalse(capture.clean(status))
            pid = int(pidfile.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_resource_failure_terminates_worker_and_escaped_child(self):
        with tempfile.TemporaryDirectory(prefix='puppybot-l5-abort-') as directory:
            root = pathlib.Path(directory)
            (root / 'outer-monitor').mkdir()
            pidfile = root / 'pids'
            code = ('import os,subprocess,sys,time;'
                    'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],start_new_session=True);'
                    'open(sys.argv[1],"w").write(str(os.getpid())+" "+str(p.pid));'
                    'time.sleep(60)')
            with (mock.patch.object(capture, 'OUTPUT', root),
                  mock.patch.object(capture, 'baseline'),
                  mock.patch.object(capture, 'sample', side_effect=[{}, RuntimeError('simulated disk floor')])):
                status = capture.supervise_monitored([sys.executable, '-c', code, str(pidfile)])
            self.assertIn('simulated disk floor', status['reason'])
            self.assertFalse(capture.clean(status))
            for pid in map(int, pidfile.read_text().split()):
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_lock_rejects_contention(self):
        with tempfile.TemporaryDirectory(prefix='puppybot-l5-lock-') as directory:
            path = pathlib.Path(directory) / 'lock'
            with capture.acquire_lock(path):
                with self.assertRaises(BlockingIOError):
                    capture.acquire_lock(path)
            with capture.acquire_lock(path):
                pass

    def test_game_rejects_surviving_descendant_before_next_game(self):
        with tempfile.TemporaryDirectory(prefix='puppybot-l5-game-') as directory:
            root = pathlib.Path(directory)
            (root / 'game-supervisors').mkdir()
            code = ('import subprocess,sys;'
                    'subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"],start_new_session=True)')
            with (mock.patch.object(capture, 'OUTPUT', root),
                  mock.patch.object(capture, 'command', return_value=[sys.executable, '-c', code])):
                with self.assertRaisesRegex(RuntimeError, 'left descendants'):
                    capture.run_game(7, 'control', 'unused')

    def test_runtime_and_sealed_original_change_are_detected(self):
        with tempfile.TemporaryDirectory(prefix='puppybot-l5-pins-') as directory:
            root = pathlib.Path(directory)
            (root / 'a').write_bytes(b'first')
            (root / 'b').write_bytes(b'second')
            (root / 'link').symlink_to('a')
            first = capture.diagnostic.runtime_chain(root / 'link')
            (root / 'link').unlink()
            (root / 'link').symlink_to('b')
            self.assertNotEqual(first, capture.diagnostic.runtime_chain(root / 'link'))
            path = root / 'record'
            path.write_bytes(b'known')
            sealed = {'record': {'sha256': capture.diagnostic.digest(path), 'size': path.stat().st_size}}
            with mock.patch.object(capture.diagnostic, 'SELECTION', root):
                capture.diagnostic.check_sealed(path, sealed)
                path.write_bytes(b'other')
                with self.assertRaisesRegex(ValueError, 'selection evidence differs'):
                    capture.diagnostic.check_sealed(path, sealed)

    def test_catalog_rejects_changed_link(self):
        with tempfile.TemporaryDirectory(prefix='puppybot-l5-catalog-') as directory:
            root = pathlib.Path(directory)
            scene = root / 'scene'
            scene.mkdir()
            paths = [scene / name for name in ('case.json', 'environment.bin', 'layout.json')]
            for path in paths:
                path.write_text(path.name)
            selection = root / 'selection'
            selection.mkdir()
            (selection / 'inputs.json').write_text(json.dumps({'files': {str(p): capture.diagnostic.digest(p) for p in paths}}))
            catalog = root / 'catalogs/7'
            catalog.mkdir(parents=True)
            (catalog / '0').symlink_to(scene, target_is_directory=True)
            game = {'seed': 7, 'scene': {'scene': str(scene)}}
            with mock.patch.object(capture, 'OUTPUT', root), mock.patch.object(capture.diagnostic, 'SELECTION', selection):
                capture.verify_catalog(game)
                (catalog / '0').unlink()
                (catalog / '0').symlink_to(root, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, 'catalog differs'):
                    capture.verify_catalog(game)

    def test_final_inventory_rejects_tampered_output(self):
        with tempfile.TemporaryDirectory(prefix='puppybot-l5-inventory-') as directory:
            root = pathlib.Path(directory)
            payload = root / 'actor-505.rgb'
            payload.write_bytes(b'original')
            plan = {'diagnostic': {'games': [], 'runtime': {}}, 'sourcePins': {}, 'selectionCompletion': {}}
            (root / 'plan.json').write_text(json.dumps(plan))
            with (mock.patch.object(capture, 'OUTPUT', root),
                  mock.patch.object(capture.diagnostic, 'diagnose', return_value=plan['diagnostic']),
                  mock.patch.object(capture, 'source_pins', return_value={}),
                  mock.patch.object(capture, 'selection_completion', return_value={}),
                  mock.patch.object(capture, 'verify_runtime')):
                (root / 'inventory.json').write_text(json.dumps(capture.inventory()))
                with contextlib.redirect_stdout(io.StringIO()):
                    capture.final_check()
                payload.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'output inventory differs'):
                    capture.final_check()
                payload.write_bytes(b'original')
                actual_inventory = capture.inventory
                def change_plan_after_scan():
                    observed = actual_inventory()
                    (root / 'plan.json').write_text(json.dumps(dict(plan, changed=True)))
                    return observed
                with mock.patch.object(capture, 'inventory', side_effect=change_plan_after_scan):
                    with self.assertRaisesRegex(ValueError, 'plan or inventory changed'):
                        capture.final_check()


if __name__ == '__main__':
    unittest.main()
