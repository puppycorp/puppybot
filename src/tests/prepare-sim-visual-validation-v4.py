#!/usr/bin/env python3
"""Prepare a NEW case-compatible validation plan from the retained v3 inputs.

Usage: prepare-sim-visual-validation-v4.py PILOT V3_INPUTS NEW_OUTPUT
Only the three room case controller fields change from rgb-find-return to
rgb-discovery. Geometry and all other parsed case fields remain unchanged.
A CPU-only probe uses the archived simulator parsers; rendered startup,
collision-free reset and physical task behavior remain unverified. No GPU job
or evaluation is launched, and this plan is not compatible with the v3 runner
without separately reviewed changes.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


runner=load('v3_runner',ROOT/'flex/tests/run-sim-visual-validation.py')
preflight=load('physical_preflight',ROOT/'flex/tests/physical-case-preflight.py')


def adapt(source):
    data=json.loads(source)
    if data.get('schema')!='puppybot.case.v1' or data.get('controller')!='rgb-find-return' or not isinstance(data.get('objects'),list) or len(data['objects'])!=1:
        raise ValueError('room source must be a single-object rgb-find-return case')
    modified=dict(data);modified['controller']='rgb-discovery'
    return (json.dumps(modified,sort_keys=True,indent=2)+'\n').encode()


def verify_transformation(source,derived):
    before=json.loads(source);after=json.loads(derived)
    if before.get('controller')!='rgb-find-return' or after.get('controller')!='rgb-discovery':raise ValueError('wrong room controller transformation')
    expected=dict(before);expected['controller']='rgb-discovery'
    if after!=expected:raise ValueError('room case changed beyond controller')


def prepare(pilot,v3,output):
    pilot=Path(pilot).absolute();v3=Path(v3).absolute();output=Path(output).absolute()
    if output.exists() or output.is_symlink():raise ValueError('destination exists; retain prior evidence')
    _,matrix=runner.check_matrix(pilot,v3)
    # Inspect v3 before writing any new plan, and verify that exactly the known
    # three room cases are rejected by the archived case-mode parser.
    with tempfile.TemporaryDirectory(prefix='puppy-physical-compat-') as tmp:
        probe=preflight.build_probe(pilot,tmp);old_results={}
        for condition in matrix['conditions']:
            name=condition['name'];old_results[name]=preflight.check(probe,v3/name/'case.json',v3/name/'environment.bin')
            expected=name.startswith('room-')
            result=old_results[name]
            if expected:
                if result['accepted'] or result['returnCode']!=3 or result['stderr']!='physical-agent controller incompatible':raise ValueError('unexpected v3 room compatibility result')
            elif not result['accepted']:
                raise ValueError('unexpected v3 apartment compatibility result')
        output.mkdir(parents=False,exist_ok=False);conditions=[]
        for condition in matrix['conditions']:
            name=condition['name'];source_case=(v3/name/'case.json').read_bytes();env=(v3/name/'environment.bin').read_bytes()
            if name.startswith('room-'):
                case=adapt(source_case);verify_transformation(source_case,case);change='rgb-find-return -> rgb-discovery'
            else:
                case=source_case;change='none'
            target=output/name;target.mkdir();(target/'case.json').write_bytes(case);(target/'environment.bin').write_bytes(env)
            parsed=preflight.check(probe,target/'case.json',target/'environment.bin')
            if not parsed['accepted']:raise ValueError('derived case rejected by archived parser: '+name)
            row=dict(condition);row.update({'caseSHA256':preflight.sha(target/'case.json'),'environmentSHA256':preflight.sha(target/'environment.bin'),
                                           'v3CaseSHA256':preflight.sha(v3/name/'case.json'),'caseControllerChange':change,
                                           'cpuParserPreflight':parsed})
            conditions.append(row)
    report={'schema':'puppybot.visual-stop-validation-plan.v4','status':'cpu_parser_preflight_only','sourceV3':str(v3),
            'sourceV3ManifestSHA256':preflight.sha(v3/'conditions.json'),'pilot':str(pilot),
            'preflightSHA256':preflight.sha(ROOT/'flex/tests/physical-case-preflight.py'),
            'planGeneratorSHA256':preflight.sha(Path(__file__)),'conditions':conditions,
            'oldV3Preflight':old_results,'renderedStartupVerified':False,'collisionFreeResetVerified':False,
            'scope':'separate predeclared plan; room controller semantics changed to physical discovery; original geometry and other case fields preserved; no GPU, startup, hardware or held-out claim'}
    (output/'conditions.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    return report


if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit(__doc__)
    try:
        report=prepare(*sys.argv[1:]);print(json.dumps({'status':report['status'],'conditions':len(report['conditions']),'scope':report['scope']}))
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as error:
        raise SystemExit(f'Cannot prepare v4 plan: {error}')
