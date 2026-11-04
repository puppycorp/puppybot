#!/usr/bin/env python3
"""Stage outer monitoring for the three-arm handoff-hint diagnostic.

The launch CLI remains disabled pending independent review and scheduling.
The /proc monitor samples processes and HIP mappings; it cannot attest GPU
execution, exclusive use, or an unobserved process. No hardware claim.
"""
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'build/flex/sim/levels-v2/pitch82'
RUN=BASE/'physical-handoff-hint-trial-v1'
MONITOR=BASE/'physical-handoff-hint-trial-v1-monitor'
RUNNER=ROOT/'flex/tests/run-physical-handoff-hint.py'
TELEMETRY=ROOT/'flex/tests/supervise-handoff-process.py'
WALL_SECONDS=1800  # 3*300 s arms, two 300 s audits, 300 s setup/cleanup allowance.


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


runner=load('handoff_runner',RUNNER)
sha=runner.sha


def worker(output):
    runner.run(output)
    auditor=load('handoff_reaudit',ROOT/'flex/tests/audit-physical-handoff-hint.py')
    saved=json.loads((Path(output)/'audit.json').read_text())
    if auditor.audit(output)!=saved:raise ValueError('saved audit differs from independent re-audit')


def launch_command(output,monitor):
    code=('import importlib.util,sys;'
          's=importlib.util.spec_from_file_location("handoff",sys.argv[1]);'
          'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.worker(sys.argv[2])')
    return [sys.executable,'-I',str(TELEMETRY),str(monitor/'process-telemetry'),'--',sys.executable,'-I','-c',code,str(Path(__file__).resolve()),str(output)]


def verified_result(status,telemetry,audit):
    if (status.get('clientExit')!=2 or status.get('timedOut') is not False or status.get('signal') is not None
            or status.get('remainingWorkersTerminated') is not False):raise ValueError('outer supervision failed; partial evidence retained')
    if (telemetry.get('event')!='end' or telemetry.get('exitCode')!=0 or telemetry.get('errors')!=[]
            or telemetry.get('hipFileUnchanged') is not True or type(telemetry.get('observedPolicies')) is not int
            or telemetry['observedPolicies']<1 or telemetry.get('policiesWithExpectedHipFileMapping')!=telemetry['observedPolicies']
            or telemetry.get('eligibleForQualification') is not False):raise ValueError('process telemetry incomplete or failed')
    arms=audit.get('arms')
    if (audit.get('status')!='diagnostic_only' or type(audit.get('comparisonEligible')) is not bool or not isinstance(arms,list)
            or [a.get('arm') for a in arms]!=['original','candidate-disabled','candidate-enabled']
            or any(a.get('status') not in ('completed','censored') for a in arms)):raise ValueError('missing or malformed diagnostic audit')
    return {'status':'diagnostic_only','comparisonEligible':audit['comparisonEligible'],
            'scope':'sampled process telemetry; observing one policy does not establish all three were observed; no attestation, GPU exclusivity, or hardware claim'}


def launch(output=RUN,monitor=MONITOR):
    output=Path(output).absolute();monitor=Path(monitor).absolute()
    if output==monitor or output.exists() or output.is_symlink() or monitor.exists() or monitor.is_symlink():raise ValueError('output or monitor exists; retain evidence')
    if shutil.disk_usage(output.parent).free<12*1024**3:raise ValueError('insufficient space before monitored launch')
    build,_=runner.check()
    paths=[Path(__file__),RUNNER,TELEMETRY,ROOT/'flex/tests/audit-physical-handoff-hint.py',
           ROOT/'flex/tests/run-physical-hidden-trial.py',ROOT/'flex/tests/run-physical-rescan-trial.py',
           ROOT/'flex/tests/prepare-physical-handoff-hint.py',Path(sys.executable).resolve()]
    pinned={str(path):sha(path) for path in paths}
    env={'PATH':'/usr/bin:/bin','HOME':str(Path.home()),'SDL_VIDEODRIVER':'offscreen',
         'LD_LIBRARY_PATH':str(ROOT/'build/flex/rocm-runtime')}
    monitor.mkdir(mode=0o700)
    command=launch_command(output,monitor)
    receipt={'schema':'puppybot.handoff-hint-outer-monitor.v1','command':command,'environment':env,
             'files':pinned,'candidateSHA256':build['candidateSimulatorSHA256'],'wallSeconds':WALL_SECONDS,
             'scope':'outer watchdog and sampled /proc telemetry; no authentication or physical-hardware claim'}
    (monitor/'launch.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
    status=runner.hidden.supervise(command,monitor,env,WALL_SECONDS)
    if any(sha(Path(path))!=digest for path,digest in pinned.items()):raise ValueError('outer launcher inputs changed; retain evidence')
    events=[json.loads(line) for line in (monitor/'process-telemetry/observations.jsonl').read_text().splitlines()]
    if not events:raise ValueError('empty process telemetry')
    audit=json.loads((output/'audit.json').read_text())
    result=verified_result(status,events[-1],audit)
    (monitor/'result.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    return result


if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='--check':
        build,_=runner.check();print(json.dumps({'status':'cpu_preflight_only','candidateSHA256':build['candidateSimulatorSHA256'],'scope':'no GPU or simulator run'}))
    else:raise SystemExit('GPU execution disabled pending independent review and a scheduling decision.')
