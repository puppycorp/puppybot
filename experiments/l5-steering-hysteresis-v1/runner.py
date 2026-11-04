#!/usr/bin/env python3
"""Disabled three-arm simulator runner; outer GPU monitor not yet supplied."""
import importlib.util
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
ARM_SECONDS=600


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


registration=load('hys_runner_registration',HERE/'register.py');plan=registration.plan;base=registration.base
audit=load('hys_saved_audit',HERE/'audit.py')
selection=load('hys_selection_snapshot',ROOT/'datasets/visual-control/chase-v1/levels/audit-selection.py')
guard=load('hys_dedicated_process',ROOT/'experiments/sim-stop-supervisor/supervisor.py')


def environment():return {'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen','LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime')}


def command(row,arm):
    if arm not in plan.design()['arms']:raise ValueError('invalid arm')
    output=plan.OUTPUT/'games'/str(row['index'])/arm;flag='--steer-probe-control' if arm=='control' else '--steer-probe-enabled'
    argv=[str(plan.BUILD/'control'),'run','--fetch','--policy',str(plan.MODEL),'--scene',row['scene'],'--output',str(output),
          '--episodes','1','--horizon','300','--seed',str(row['seed']),'--level','5','--lean','--wheel-odometry','--camera-pitch','82',flag]
    if arm=='kick-hysteresis':argv.append('--steer-hysteresis')
    return argv


def write_new(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')


def clean(status):
    if ('signal' not in status or type(status.get('clientExit')) is not int or status['clientExit']!=0 or status.get('signal') is not None or
            status.get('timedOut') is not False or status.get('remainingWorkersTerminated') is not False or type(status.get('processGroup')) is not int or status['processGroup']<=0):raise ValueError('unclean arm supervisor')


def live_check(manifest):
    current=registration.current(include_history=False);expected=dict(manifest);expected['history']=None
    if current!=expected:raise ValueError('registered nonhistory inputs changed')


def reaudit(manifest):
    if json.loads((plan.OUTPUT/'inputs.json').read_text())!=manifest or manifest.get('status')!='frozen_before_play' or manifest.get('design')!=plan.design() or len(manifest.get('scenes',[]))!=12:raise ValueError('input manifest differs')
    pairs=[]
    for row,expected in zip(manifest['scenes'],plan.design()['conditions']):
        if any(row.get(k)!=v for k,v in expected.items()):raise ValueError('scene row differs')
        for arm in plan.design()['arms']:
            output=plan.OUTPUT/'games'/str(row['index'])/arm;monitor=plan.OUTPUT/'monitors'/str(row['index'])/arm
            if json.loads((monitor/'invocation.json').read_text())!={'argv':command(row,arm),'environment':environment(),'wallSeconds':ARM_SECONDS}:raise ValueError('arm invocation differs')
            clean(json.loads((monitor/'supervisor-result.json').read_text()))
            if selection.snapshot(output/'policy',plan.MODEL)!=manifest['files'][str(plan.MODEL/'weights.bin')]:raise ValueError('policy snapshot differs')
        games=[plan.OUTPUT/'games'/str(row['index'])/arm/str(row['seed']) for arm in plan.design()['arms']]
        expected_input={'weightsSHA256':manifest['files'][str(plan.MODEL/'weights.bin')],'case.json':row['files']['case.json'],'environment.bin':row['files']['environment.bin']}
        pairs.append(audit.saved_three(*games,row['seed'],expected_input))
    return audit.report(pairs)


def run():
    guard.require_dedicated_process()
    with base.acquire_lock(plan.P/'.l4-matched.lock'):
        base.require_new_output(plan.OUTPUT);base.require_capacity(plan.P,36*1024**3);manifest=registration.verify()
        plan.OUTPUT.mkdir();write_new(plan.OUTPUT/'inputs.json',manifest);(plan.OUTPUT/'games').mkdir();(plan.OUTPUT/'monitors').mkdir();finished=[]
        try:
            for row in manifest['scenes']:
                game=plan.OUTPUT/'games'/str(row['index']);game.mkdir();monitors=plan.OUTPUT/'monitors'/str(row['index']);monitors.mkdir()
                for arm in plan.design()['arms']:
                    base.require_capacity(plan.P,34*1024**3);live_check(manifest);monitor=monitors/arm;monitor.mkdir();argv=command(row,arm);env=environment()
                    write_new(monitor/'invocation.json',{'argv':argv,'environment':env,'wallSeconds':ARM_SECONDS})
                    status=base.hidden.supervise(argv,monitor,env,ARM_SECONDS);clean(status)
                    if json.loads((monitor/'supervisor-result.json').read_text())!=status:raise ValueError('saved supervisor status differs')
                    live_check(manifest);finished.append({'index':row['index'],'arm':arm})
            report=reaudit(manifest);live_check(manifest)
            if registration.verify()!=manifest:raise ValueError('history or inputs changed during trial')
            base.require_capacity(plan.P,32*1024**3);write_new(plan.OUTPUT/'report.json',report);return report
        except BaseException as error:
            if not (plan.OUTPUT/'report.json').exists():write_new(plan.OUTPUT/'partial.json',{'status':'censored','finished':finished,'reason':str(error)})
            raise


if __name__=='__main__':raise SystemExit('Disabled pending independent review and a monitored execution plan.')
