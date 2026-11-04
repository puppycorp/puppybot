#!/usr/bin/env python3
"""Bound the whole four-game heading roll-in pilot, including its CPU audits.

First prepare the pilot catalogs. Run only after independent review, when the
GPU is otherwise idle. The 30-minute watchdog retains all output on failure;
it does not attest GPU exclusivity or make the pilot a held-out evaluation.
"""
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[4]
S = PROJECT / 'datasets/visual-control/chase-v1/levels'
P = PROJECT / 'build/flex/sim/levels-v2/pitch82'
MONITOR = P / 'heading-rollin-pilot-supervisor'
PILOT = P / 'search-dagger-heading-pilot'
CATALOGS = P / 'heading-rollin-pilot-catalogs'
WALL_SECONDS = 1800


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


base = load('route_runner', S / 'run-route-factorial.py')


def require_terminal(status, report):
    base.require_success(status, MONITOR)
    if report.get('status') != 'passed' or report.get('mode') != 'pilot':
        raise ValueError('bounded pilot did not publish a passing pilot report')


def main():
    if len(sys.argv) != 1: raise SystemExit(__doc__)
    os.chdir(PROJECT)
    base.require_capacity(P, 40 * 1024**3)
    base.require_new_output(MONITOR); base.require_new_output(PILOT)
    if not (CATALOGS / 'catalogs.json').is_file(): raise ValueError('prepare the pilot catalogs first')
    command = [sys.executable, '-I', str(S / 'run-heading-rollin.py'), 'pilot']
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'PUPPYBOT_PROJECT': str(PROJECT),
           'LD_LIBRARY_PATH': str(PROJECT / 'build/flex/rocm-runtime'), 'SDL_VIDEODRIVER': 'offscreen'}
    MONITOR.mkdir()
    launch = {'command': command, 'wallSeconds': WALL_SECONDS, 'wrapperSHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'scope': 'external bounded supervision only; output and partial data retained'}
    (MONITOR / 'launch.json').write_text(json.dumps(launch, indent=2, sort_keys=True) + '\n')
    status = base.hidden.supervise(command, MONITOR, env, WALL_SECONDS)
    base.require_success(status, MONITOR)
    report = json.loads((PILOT / 'pilot-report.json').read_text())
    require_terminal(status, report)
    print(json.dumps({'status': 'passed', 'pilot': str(PILOT), 'supervisor': str(MONITOR), 'wallSeconds': status['wallSeconds']}))


if __name__ == '__main__': main()
