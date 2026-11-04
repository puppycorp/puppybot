#!/usr/bin/env python3
"""CPU-only design and semantic checks; does not collect or train."""
import copy
import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan = load('retention_plan', HERE / 'plan.py')
audit = load('retention_lineage', HERE / 'audit.py')


def fixture():
    rows = []
    for i, (index, layout, variant) in enumerate(plan.EXPECTED):
        rows.append({'shard': i // 2, 'episode': i % 2, 'role': 'fit' if i % 2 == 0 else 'companion_only',
                     'seed': plan.SEEDS[i], 'layout': layout, 'variant': variant,
                     'firstDeliveryStep': {0: 163, 2: 189}.get(i)})
    return {'schema': 'puppybot.parent-route-collector-plan.v1', 'status': 'cpu_plan_only',
            'rows': rows, 'commands': [plan.command(0), plan.command(1)],
            'semantics': {'actor': 'parent policy chooses and executes each action',
                          'data': 'PVDATA01 pre-action RGB and feedback, teacher action label, map',
                          'journal': 'decisions[i].action is the executed action; state/proprio are post-step',
                          'selfImitation': False, 'fitting': 'episode 0 of each shard only; companions never added',
                          'gate': 'must independently audit full collection, first-delivery prefix and label differences'},
            'environment': {'PATH': '/usr/bin:/bin', 'HOME': str(pathlib.Path.home()),
                            'SDL_VIDEODRIVER': 'offscreen', 'PUPPYBOT_PROJECT': str(plan.ROOT),
                            'LD_LIBRARY_PATH': str(plan.ROOT / 'build/flex/rocm-runtime')}}


class PlanTests(unittest.TestCase):
    def test_exact_fit_and_companion_split(self):
        result = fixture()
        self.assertEqual(len(audit.validate_design(result)), 4)
        for index in (1, 3):
            changed = copy.deepcopy(result)
            changed['rows'][index]['role'] = 'fit'
            with self.assertRaisesRegex(ValueError, 'fit/companion'):
                audit.validate_design(changed)

    def test_supervision_and_command_mutations_are_rejected(self):
        result = fixture()
        for flag in ('--self-imitate', '--sample-actions', '--hide-carry'):
            changed = copy.deepcopy(result)
            changed['commands'][0].append(flag)
            with self.assertRaisesRegex(ValueError, 'collector command'):
                audit.validate_design(changed)
        changed = copy.deepcopy(result)
        changed['commands'][0][changed['commands'][0].index('--validation') + 1] = '0'
        with self.assertRaisesRegex(ValueError, 'collector command'):
            audit.validate_design(changed)
        changed = copy.deepcopy(result)
        changed['semantics']['data'] = 'policy action labels'
        with self.assertRaisesRegex(ValueError, 'collector command or supervision'):
            audit.validate_design(changed)

    def test_missing_pinned_inputs_are_rejected_before_lineage(self):
        result = fixture()
        result['inputSHA256'] = {}
        with self.assertRaisesRegex(ValueError, 'pinned input inventory differs'):
            audit.audit(result)

    def test_collection_source_orders_preaction_rows_and_executed_actions(self):
        source = (plan.ROOT / 'flex/control/chase.flex').read_text()
        begin = source.index('fn vx_episode(')
        body = source[begin:source.index('fn vx_scene(', begin)]
        label = body.index('vx_fetch_teacher(label)')
        action = body.index('let output=ve_action(hidden,vw_blackout)')
        self_label = body.index('if vw_self_keep || vw_sample_actions {vc_copy(label,action,8);}')
        data = body.index('vc_copy(row+28,label,8)')
        step = body.index('ve_step(action)')
        self.assertLess(label, action)
        self.assertLess(action, self_label)
        self.assertLess(self_label, data)
        self.assertLess(data, step)
        self.assertIn('if vw_self_keep {pb_put32(row+40,0);}', body)
        self.assertIn('pb_put32(base+vw_horizon*21168+t*44+40,0x3f800000)', body)


if __name__ == '__main__':
    unittest.main()
