#!/usr/bin/env python3
"""CPU-only source-build and saved-probe auditor tests; never runs a GPU."""
import copy
import hashlib
import importlib.util
import json
import math
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


transform = load('transform'); audit = load('audit'); plan = load('plan')
ZERO_HIDDEN = hashlib.sha256(bytes(512)).hexdigest()


def generated(mode, triggered=True, carry_at=None):
    rows = []; decisions = []; previous = [0, 0]; hidden = ZERO_HIDDEN; prior_drive = [0, 0, 90]
    for i in range(300):
        proposed = [audit.bits(-.6 if triggered else .6), audit.bits(-1.)]
        carry = carry_at is not None and i >= carry_at
        applied = list(proposed)
        if mode == 2 and triggered and not carry and i < 3: applied[0] = audit.sign_flip(applied[0])
        steering, speed = [audit.value(x) for x in applied]; command = [round(steering * 1000), round(speed * 1000)]
        throttle = math.trunc(command[1] * 60 / 1000) if abs(command[1]) >= 80 else 0
        echo = [throttle, throttle, 90 + math.trunc(math.trunc(command[0] / 10) * 45 / 100)]
        feedback = previous + [audit.bits(prior_drive[0]/100), audit.bits(prior_drive[1]/100),
                               audit.bits((prior_drive[2]-90)/45), audit.bits(0.), audit.bits(float(carry))]
        after = hashlib.sha256(str(i).encode()).hexdigest()
        rows.append({'step': i+1, 'mode': mode, 'trigger': triggered, 'cancelled': carry,
                     'proposed': proposed, 'applied': applied, 'feedback': feedback, 'previousApplied': applied,
                     'command1000': command, 'echo': echo, 'imageSHA256': 'a'*64,
                     'hiddenBeforeSHA256': hidden, 'hiddenAfterSHA256': after})
        post_carry = carry_at is not None and i >= carry_at - 1
        decisions.append({'action': [steering, speed], 'state': {'controller': {'drive':
                          {'leftSpeed': echo[0], 'rightSpeed': echo[1], 'steeringAngleDeg': echo[2]}},
                          'findReturn': {'consumedIndex': 0 if post_carry else -1, 'deliveries': 0}}})
        previous = applied; prior_drive = echo; hidden = after
    return rows, decisions


class ProbeTests(unittest.TestCase):
    def test_fixed_plan_is_balanced_and_not_registered(self):
        d = plan.design(); rows = d['conditions']
        self.assertEqual(d['status'], 'draft_not_registered'); self.assertEqual(len(rows), 12)
        self.assertEqual([r['layout'] for r in rows], [13]*4 + [15]*4 + [17]*4)
        self.assertEqual(len({r['seed'] for r in rows}), 12); self.assertEqual(len({r['scene'] for r in rows}), 12)
        self.assertEqual(d['screen']['minimumTriggered'], 6); self.assertEqual(d['screen']['minimumAdditionalConsumedByAction200'], 3)
        self.assertIn('including no-ops', d['denominator']); self.assertIn('inventories', d['prerequisite'])

    def test_source_transform_is_strict_and_native_probe_passes(self):
        chase = (ROOT / 'flex/control/chase.flex').read_text(); main = (ROOT / 'flex/control/main.flex').read_text()
        changed, changed_main = transform.transform(chase, main)
        self.assertIn('vx_probe_capture(hidden)', changed); self.assertIn('vx_probe_emit(action,hidden)', changed)
        self.assertIn('--steer-probe-enabled', changed_main)
        with self.assertRaises(ValueError): transform.transform(changed, main)
        with self.assertRaises(ValueError): transform.transform(chase, main.replace('--fetch', '--missing-fetch'))
        with tempfile.TemporaryDirectory(prefix='steer-native-test-') as tmp:
            root = Path(tmp); shutil.copytree(ROOT / 'flex', root / 'flex')
            (root / 'flex/control/chase.flex').write_text(changed); (root / 'flex/control/main.flex').write_text(changed_main)
            shutil.copyfile(HERE / 'probe.flex', root / 'flex/control/steer-probe.flex')
            compiler = ROOT / 'build/flex/control/compiler'
            for source, output in [('main.flex','control'), ('steer-probe.flex','probe')]:
                subprocess.run([str(compiler), str(root / 'flex/control' / source), '-o', str(root / output)],
                               cwd=ROOT, check=True, capture_output=True, timeout=120)
            result = subprocess.run([str(root / 'probe'), str(root)], check=True, capture_output=True, text=True, timeout=10)
            self.assertIn('CPU checks passed', result.stdout)
            records = [json.loads(line) for line in (root / 'steer-probe.jsonl').read_text().splitlines()]
            self.assertEqual(len(records), 1); record = records[0]
            self.assertEqual(record['proposed'], [audit.bits(-.6), audit.bits(-1.)])
            self.assertEqual(record['applied'], [audit.bits(.6), audit.bits(-1.)])
            self.assertEqual(record['previousApplied'], record['applied'])
            self.assertEqual(record['feedback'], [0] * 7)
            self.assertEqual(record['command1000'], [600, -1000]); self.assertEqual(record['echo'], [-60, -60, 117])
            self.assertEqual(record['hiddenBeforeSHA256'], ZERO_HIDDEN)
            base = [str(root / 'control'), 'run', '--fetch', '--policy', str(root / 'missing-model'),
                    '--output', str(root / 'forbidden-output'), '--episodes', '1', '--horizon', '300',
                    '--wheel-odometry', '--camera-pitch', '82', '--level', '5', '--steer-probe-enabled']
            for extra in (['--blackout'], ['--hide-carry'], ['--search-cue'], ['--image-128'], ['--straight-bias','50']):
                rejected = subprocess.run(base + extra, cwd=ROOT, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn('steer probe requires the fixed', rejected.stderr)
                self.assertFalse((root / 'forbidden-output').exists())

    def test_triggered_pair_and_noop_are_counted(self):
        control = generated(1); treatment = generated(2)
        result = audit.audit_pair(control, treatment)
        self.assertTrue(result['control']['triggered']); self.assertEqual(result['intervention']['changedActions'], 3)
        self.assertEqual(result['firstChangedAction'], 1)
        result = audit.audit_pair(generated(1, False), generated(2, False))
        self.assertFalse(result['control']['triggered']); self.assertIsNone(result['firstChangedAction'])
        result = audit.audit_stream(*generated(2, True, 1), 2)
        self.assertEqual(result['changedActions'], 1); self.assertTrue(result['carryingCancelled'])

    def test_corrupt_feedback_actions_hidden_echo_and_prefix_are_rejected(self):
        for mutation in ('missing', 'invalid-trigger', 'speed-changed', 'post-window', 'feedback', 'wheel-feedback', 'hidden', 'drive', 'prefix', 'false-cue'):
            control = generated(1); treatment = generated(2); rows, decisions = treatment
            if mutation == 'missing': rows.pop()
            elif mutation == 'invalid-trigger': rows[0]['trigger'] = False
            elif mutation == 'speed-changed': rows[0]['applied'][1] = audit.bits(1.)
            elif mutation == 'post-window': rows[4]['applied'][0] = audit.sign_flip(rows[4]['applied'][0])
            elif mutation == 'feedback': rows[1]['feedback'][0] = 0
            elif mutation == 'wheel-feedback': rows[1]['feedback'][2] = 0
            elif mutation == 'hidden': rows[1]['hiddenBeforeSHA256'] = 'b'*64
            elif mutation == 'drive': decisions[0]['state']['controller']['drive']['leftSpeed'] = 1
            elif mutation == 'false-cue': rows[1]['feedback'][6] = audit.bits(1.)
            else: rows[0]['imageSHA256'] = 'b'*64
            with self.subTest(mutation=mutation), self.assertRaises((ValueError, KeyError)):
                audit.audit_pair(control, treatment)

        rows, decisions = generated(2, True, 1); rows[1]['feedback'][6] = audit.bits(0.)
        with self.assertRaisesRegex(ValueError, 'carry cue'): audit.audit_stream(rows, decisions, 2)

    def test_fixed_screen_includes_noops_and_rejects_missing_games(self):
        pairs = [{'seed': 6800100+i, 'triggered': i < 6, 'controlEarly': False,
                  'interventionEarly': i < 3, 'controlDelivered': False, 'interventionDelivered': False,
                  'controlMostlyBackForth': False, 'interventionMostlyBackForth': False} for i in range(12)]
        result = audit.screen(pairs)
        self.assertEqual(result['status'], 'exploratory_screen_passed')
        self.assertEqual(result['games'], 12); self.assertEqual(result['totals']['triggered'], 6)
        pairs[0]['interventionMostlyBackForth'] = True
        self.assertEqual(audit.screen(pairs)['status'], 'exploratory_screen_not_passed')
        with self.assertRaises(ValueError): audit.screen(pairs[:-1])
        pairs[0]['interventionMostlyBackForth'] = None
        with self.assertRaises(ValueError): audit.screen(pairs)
        pairs[0]['interventionMostlyBackForth'] = False; pairs[0]['seed'] = 123
        with self.assertRaises(ValueError): audit.screen(pairs)

    def test_saved_pair_binds_scenes_start_actions_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); case = b'{}'; environment = bytearray(384); environment[:8] = b'PBENV001'; struct.pack_into('<q', environment, 8, 1); environment[256:270] = b'Wall.partition'; struct.pack_into('<d', environment, 304, 1.)
            struct.pack_into('<3d', environment, 96, -.04, -.04, .42)
            expected = {'case.json': hashlib.sha256(case).hexdigest(),
                        'environment.bin': hashlib.sha256(environment).hexdigest(), 'weightsSHA256': 'weights'}
            result = {'seed': 6800100, 'steps': 300, 'game': 'fetch', 'level': 5, 'levelPlacement': 'other room',
                      'controller': 'native neural policy', 'blackout': False, 'farBricks': False,
                      'exploreTeacher': False, 'sweepTeacher': False, 'suppliedMap': False,
                      'taskEventHint': False, 'carryCue': True, 'policyWeightsSHA256': 'weights',
                      'reaches': 0, 'deliveries': 0, 'backForthSteps': 0, 'contactSteps': 0, 'maximumBrickDistanceM': .35}
            start = {'event': 'start', 'step': 0, 'robot': [-.04,-.04,.42], 'brick': [2.,3.]}
            initial = {'pose': start['robot'], 'step': 495, 'controller': {'drive':
                       {'leftSpeed': 0, 'rightSpeed': 0, 'steeringAngleDeg': 90}}}
            for name, mode in (('control', 1), ('intervention', 2)):
                game = root / name; (game / 'scene').mkdir(parents=True)
                (game / 'scene/case.json').write_bytes(case); (game / 'scene/environment.bin').write_bytes(environment)
                (game / 'result.json').write_text(json.dumps(result)); (game / 'initial.json').write_text(json.dumps(initial))
                (game / 'chase.jsonl').write_text(json.dumps(start)+'\n')
                rows, decisions = generated(mode)
                for i, decision in enumerate(decisions):
                    decision['step'] = 505 + i*10; decision['sequence'] = i+3
                    state = decision['state']; state['pose'] = [i*.01,0.,0.]
                    state['ball'] = [2.,3.,.01]; state['trainingOracle'] = {'enabled': False, 'queries': 0}
                    state['localization'] = {'mode': 'wheel-drift', 'pose': [i*.01,0.,0.]}
                    state['findReturn'] = {'phase':'search', 'consumedIndex':-1, 'deliveries':0}
                (game / 'decisions.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in decisions))
                (game / 'steer-probe.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
            pair = audit.saved_pair(root/'control', root/'intervention', 6800100, expected)
            self.assertTrue(pair['triggered']); self.assertFalse(pair['controlEarly'])
            self.assertEqual(pair['controlMetrics']['firstConsumptionCappedAction'], 301)
            self.assertEqual(pair['controlMetrics']['firstRoomEntryAction'], 102)
            self.assertEqual(pair['controlMetrics']['recordedContactSteps'], 0)
            bad_result = dict(result, maximumBrickDistanceM=.4)
            (root/'intervention/result.json').write_text(json.dumps(bad_result))
            with self.assertRaisesRegex(ValueError, 'maximumBrickDistanceM'):
                audit.saved_pair(root/'control', root/'intervention', 6800100, expected)
            (root/'intervention/result.json').write_text(json.dumps(result))
            decision_path = root/'intervention/decisions.jsonl'; original = decision_path.read_text()
            changed_rows = [json.loads(line) for line in original.splitlines()]
            changed_rows[0]['state']['trainingOracle']['queries'] = False
            decision_path.write_text(''.join(json.dumps(row)+'\n' for row in changed_rows))
            with self.assertRaisesRegex(ValueError, 'oracle'):
                audit.saved_pair(root/'control', root/'intervention', 6800100, expected)
            decision_path.write_text(original)
            (root/'intervention/initial.json').write_text('{}')
            with self.assertRaises((ValueError, KeyError)): audit.saved_pair(root/'control', root/'intervention', 6800100, expected)
            (root/'intervention/scene/case.json').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'scene snapshot'): audit.saved_pair(root/'control', root/'intervention', 6800100, expected)


if __name__ == '__main__': unittest.main()
