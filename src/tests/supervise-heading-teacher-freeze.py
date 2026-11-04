#!/usr/bin/env python3
"""Disabled standalone CPU watchdog for teacher-plan registration only."""
import importlib.util
import json
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
OUTPUT = P / 'search-dagger-heading'
PLAN = OUTPUT / 'models/heading-teacher-plan-v1.json'
TEACHER = OUTPUT / 'teacher-selection-v1'
TEACHER_MONITOR = P / 'heading-teacher-selection-monitored-v1'
STUDENT_RECEIPT = P / 'heading-selection-monitored-v1/completion.json'
MONITOR = P / 'heading-teacher-freeze-cpu-monitor-v1'
FREEZE = ROOT / 'datasets/visual-control/chase-v1/levels/heading-teacher-frozen-v1.py'
WALL_SECONDS = 10800
GIB = 1024**3


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


watch = load('overlay_cpu_watchdog', ROOT / 'flex/tests/supervise-heading-overlays.py')
base = watch.base


def check_published_plan(expected_source, expected_student):
    plan = json.loads(PLAN.read_text())
    tasks = plan.get('draft', {}).get('tasks', [])
    if (plan.get('schema') != 'puppybot.heading-teacher-selection-plan.v1' or
            plan.get('status') != 'frozen_before_teacher' or
            [task.get('name') for task in tasks] != ['standard', 'L1', 'L2', 'L3', 'L4', 'L5'] or
            plan.get('studentCompletionSHA256') != expected_student or
            plan.get('sourcePins', {}).get(str(FREEZE)) != expected_source):
        raise ValueError('published teacher plan metadata differs')


def launch():
    """Use only in an isolated, single-threaded process with no children."""
    if threading.active_count() != 1 or watch.native_task_count() != 1 or watch.hidden.supervisor.children(os.getpid()):
        raise RuntimeError('teacher freeze supervisor requires a dedicated process without other children')
    if not STUDENT_RECEIPT.is_file(): raise ValueError('monitored student selection completion is missing')
    base.require_capacity(P, 38 * GIB)
    for path in (MONITOR, PLAN, TEACHER, TEACHER_MONITOR): base.require_new_output(path)
    source_sha = base.sha(FREEZE); student_sha = base.sha(STUDENT_RECEIPT)
    code = ('import importlib.util,json,sys;'
            's=importlib.util.spec_from_file_location("teacher_frozen",sys.argv[1]);'
            'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
            'p=m.freeze();print(json.dumps({"status":p["status"]},sort_keys=True))')
    command = [sys.executable, '-I', '-c', code, str(FREEZE)]
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(ROOT),
           'SDL_VIDEODRIVER': 'offscreen', 'LD_LIBRARY_PATH': str(ROOT / 'build/flex/rocm-runtime')}
    MONITOR.mkdir(parents=False, exist_ok=False)
    with (MONITOR / 'launch.json').open('x') as stream:
        json.dump({'command': command, 'environment': env, 'wallSeconds': WALL_SECONDS,
                   'freezeSourceSHA256': source_sha, 'studentCompletionSHA256': student_sha,
                   'scope': 'bounded CPU registration only; no teacher or GPU execution'}, stream, indent=2)
        stream.write('\n')
    status, code = watch.supervise(MONITOR, command, env, WALL_SECONDS)
    if code == 0:
        try:
            if base.sha(FREEZE) != source_sha or base.sha(STUDENT_RECEIPT) != student_sha:
                raise ValueError('freeze source or student receipt changed')
            check_published_plan(source_sha, student_sha)
        except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
            code = 1
    with (MONITOR / 'result.json').open('x') as stream:
        json.dump({'wrapperExit': code, 'childExit': status.get('clientExit'), 'signal': status.get('signal'),
                   'timedOut': status.get('timedOut'), 'remainingWorkersTerminated': status.get('remainingWorkersTerminated'),
                   'scope': 'saved CPU registration status only; no teacher performance claim'}, stream, indent=2)
        stream.write('\n')
    return code


if __name__ == '__main__':
    raise SystemExit('Disabled pending independent review; no teacher registration authorized.')
