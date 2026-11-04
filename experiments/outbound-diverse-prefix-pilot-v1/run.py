#!/usr/bin/env python3
"""Paired diverse pilot worker; invoke only under its external monitor."""
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan = load('diverse_outbound_worker_plan', HERE / 'plan.py')
auditor = load('diverse_outbound_worker_audit', HERE / 'audit.py')
legacy = load('diverse_outbound_supervision', ROOT / 'experiments/l5-teacher-rollin-pilot-v1/pilot.py')
P = plan.P
OUTPUT = plan.OUTPUT
standalone = legacy.standalone
base = legacy.base
sha = legacy.sha
write_new = legacy.write_new
command = plan.command


def pin_inputs():
    return plan.preflight()


def clean(status):
    return (type(status.get('clientExit')) is int and status['clientExit'] == 0 and
            status.get('signal') is None and status.get('timedOut') is False and
            status.get('remainingWorkersTerminated') is False and
            type(status.get('processGroup')) is int and status['processGroup'] > 0)


def run():
    standalone.require_dedicated_process()
    try:
        prepared = plan.prepare_catalog()
        launch = plan.freeze()
        with base.acquire_lock(P / '.l4-matched.lock'):
            inputs = pin_inputs()
            if prepared.get('inputs') != inputs or launch.get('inputs') != inputs:
                raise ValueError('frozen pilot inputs changed')
            plan.verify_catalog(inputs)
            for arm in ('student', 'teacher'):
                base.require_capacity(P, 34 * 1024**3)
                if pin_inputs() != inputs:
                    raise ValueError('pilot inputs changed before arm')
                directory = OUTPUT / f'monitor-{arm}'; directory.mkdir()
                argv = command(arm, OUTPUT / arm); env = plan.environment()
                if launch['commands'][arm] != argv or launch['environment'] != env:
                    raise ValueError('arm differs from frozen launch')
                write_new(directory / 'invocation.json', {'argv': argv, 'environment': env, 'wallSeconds': 3600})
                status = base.hidden.supervise(argv, directory, env, 3600)
                if not clean(status) or json.loads((directory / 'supervisor-result.json').read_text()) != status:
                    raise RuntimeError('pilot arm failed or required cleanup')
                if pin_inputs() != inputs:
                    raise ValueError('pilot inputs changed during arm')
            result = auditor.audit()
            if pin_inputs() != inputs:
                raise ValueError('pilot inputs changed during audit')
            base.require_capacity(P, 32 * 1024**3)
            write_new(OUTPUT / 'report.json', result)
            return result
    except BaseException as error:
        if OUTPUT.is_dir() and not (OUTPUT / 'report.json').exists() and not (OUTPUT / 'partial.json').exists():
            write_new(OUTPUT / 'partial.json', {'status': 'censored', 'reason': str(error)})
        raise


if __name__ == '__main__':
    raise SystemExit('Disabled: launch only through the reviewed dedicated monitor.')
