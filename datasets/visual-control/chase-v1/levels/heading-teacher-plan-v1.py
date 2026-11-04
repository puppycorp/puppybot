#!/usr/bin/env python3
"""Print a draft matched exploring-teacher plan. No evaluation is launched.

This draft must be reviewed, frozen and independently supervised before use;
there is currently no teacher runner or complete teacher-selection auditor.
"""
import importlib.util
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
spec = importlib.util.spec_from_file_location('heading_runner', S / 'run-heading-selection-v1.py')
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
plan_tool = runner.plan_tool
TEACHER_ROOT = plan_tool.OUTPUT / 'teacher-selection-v1'


def draft():
    tasks = []
    for task in plan_tool.selection_design():
        name = task['name']; output = TEACHER_ROOT / name
        command = ['/usr/bin/bash', str(runner.EVALUATE), str(output), 'teacher', 'teacher',
                   '--fetch', *task['levelArgs'], '--camera-pitch', '82', '--explore-teacher']
        tasks.append({'name': name, 'level': task['level'], 'rows': task['rows'],
                      'argv': command, 'environment': runner.environment(task),
                      'expectedOutput': {'score': str(output / 'score-teacher.json'),
                          'parts': [{'directory': str(output / 'teacher' / str(part)),
                                     'report': str(output / 'teacher' / str(part) / 'report.json'),
                                     'data': str(output / 'teacher' / str(part) / 'data.bin'),
                                     'log': str(output / 'teacher' / f'{part}.log'),
                                     'games': [f'expert-{i}' for i in range(8)]} for part in range(4)]}})
    return {'schema': 'puppybot.heading-exploring-teacher-draft.v1', 'status': 'draft_only',
            'teacherRoot': str(TEACHER_ROOT), 'selectionPlan': str(plan_tool.PLAN),
            'tasks': tasks, 'gamesPerTask': 32, 'actionsPerGame': 300,
            'expectedDataBytesPerPart': 32 + 8 * 300 * (21168 + 44),
            'expectedDataBytesAllParts': 24 * (32 + 8 * 300 * (21168 + 44)),
            'freezeRequirements': ['bind the registered student plan and all scene, simulator, control, runtime and asset bytes',
                'freeze this teacher plan before any teacher game, under the pitch82 shared lock',
                'use a separate no-overwrite output and a reviewed GPU/disk monitor and absolute watchdog',
                'audit all four teacher shard reports, saved games, scores, interventions and logs; compare saved initial scene, robot and brick against each candidate',
                'preserve incomplete or timed-out games as censored; require a valid monitored completion receipt'],
            'comparison': 'for each level 1–5, compare each arm total deliveries with the teacher total over the same 32 completed one-minute games; report per-game delivery fraction separately; if teacher rate is zero report absolute rates and no ratio; no automatic reliability or goal pass; result is selection-only',
            'limits': 'teacher collection writes 24 PVDATA01 datasets in addition to saved traces; teacher has wall geometry and camera detections; student uses learned policy inputs and simulator-derived carry cue; settings and initial placements can match while later placements diverge with trajectories; no OS/actor attestation, physical proof, held-out qualification, or teacher-rate goal is established'}


if __name__ == '__main__':
    print(json.dumps(draft(), indent=2, sort_keys=True))
