#!/usr/bin/env python3
"""Write a NEW CPU pre-render reset report for the frozen v4 scene plan.

Usage: verify-sim-visual-validation-v4-reset.py PILOT V3 V4 NEW_REPORT
Preserves every input and writes no GPU or simulator run. This calls the
archived ps_reset, including its simulated spawn collision query, before any
render device or case controller starts. Actual rendered startup is unproven.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


plan=load('plan',ROOT/'flex/tests/prepare-sim-visual-validation-v4.py')
reset=load('reset',ROOT/'flex/tests/physical-reset-preflight.py')


def verify(pilot,v3,v4,output):
    pilot=Path(pilot).absolute();v3=Path(v3).absolute();v4=Path(v4).absolute();output=Path(output).absolute()
    if output.exists() or output.is_symlink():raise ValueError('report destination exists')
    _,original=plan.runner.check_matrix(pilot,v3);report=json.loads((v4/'conditions.json').read_text())
    if (report.get('schema')!='puppybot.visual-stop-validation-plan.v4' or report.get('status')!='cpu_parser_preflight_only'
            or report.get('sourceV3')!=str(v3) or report.get('pilot')!=str(pilot)
            or report.get('sourceV3ManifestSHA256')!=reset.base.sha(v3/'conditions.json')
            or report.get('preflightSHA256')!=reset.base.sha(ROOT/'flex/tests/physical-case-preflight.py')
            or report.get('planGeneratorSHA256')!=reset.base.sha(ROOT/'flex/tests/prepare-sim-visual-validation-v4.py')):
        raise ValueError('v4 plan identity differs')
    expected={row['name']:row for row in original['conditions']};rows=report['conditions']
    if len(rows)!=len(expected) or {row['name'] for row in rows}!=set(expected):raise ValueError('v4 condition set differs')
    for row in rows:
        name=row['name'];source=(v3/name/'case.json').read_bytes();derived=(v4/name/'case.json').read_bytes();env=(v4/name/'environment.bin').read_bytes()
        if (env!=(v3/name/'environment.bin').read_bytes() or row['environmentSHA256']!=reset.base.sha(v4/name/'environment.bin')
                or row['caseSHA256']!=reset.base.sha(v4/name/'case.json') or row['v3CaseSHA256']!=reset.base.sha(v3/name/'case.json')):
            raise ValueError('v4 input differs: '+name)
        if name.startswith('room-'):plan.verify_transformation(source,derived)
        elif derived!=source:raise ValueError('apartment case changed')
    with tempfile.TemporaryDirectory(prefix='puppy-v4-reset-') as tmp:
        binary,asset=reset.build_probe(pilot,Path(tmp));asset_sha=reset.base.sha(asset);results=[]
        for row in rows:
            result=reset.check(binary,asset,v4/row['name']/'case.json',v4/row['name']/'environment.bin')
            results.append({'name':row['name'],'caseSHA256':row['caseSHA256'],'environmentSHA256':row['environmentSHA256'],**result})
        if reset.base.sha(asset)!=asset_sha:raise ValueError('robot asset changed during reset preflight')
        # Recheck all input bytes after the CPU probe, avoiding a stale report.
        for row in rows:
            name=row['name']
            if reset.base.sha(v4/name/'case.json')!=row['caseSHA256'] or reset.base.sha(v4/name/'environment.bin')!=row['environmentSHA256']:
                raise ValueError('v4 input changed during reset preflight')
    accepted=sum(row['accepted'] for row in results)
    result={'schema':'puppybot.visual-stop-v4-reset-report.v1','status':'all_cpu_resets_accepted' if accepted==len(results) else 'cpu_reset_rejected',
            'pilot':str(pilot),'v4':str(v4),'v4ManifestSHA256':reset.base.sha(v4/'conditions.json'),'assetSHA256':asset_sha,
            'resetPreflightSHA256':reset.base.sha(ROOT/'flex/tests/physical-reset-preflight.py'),
            'casePreflightSHA256':reset.base.sha(ROOT/'flex/tests/physical-case-preflight.py'),
            'verifierSHA256':reset.base.sha(Path(__file__)),'accepted':accepted,'cases':results,
            'scope':'archived simulator pre-render ps_reset and spawn collision check only; no graphics device, policy, rendered startup, task outcome or physical-hardware proof'}
    with output.open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2);stream.write('\n')
    return result


if __name__=='__main__':
    if len(sys.argv)!=5:raise SystemExit(__doc__)
    try:
        result=verify(*sys.argv[1:]);print(json.dumps({'status':result['status'],'accepted':result['accepted'],'total':len(result['cases'])}))
        if result['status']!='all_cpu_resets_accepted':raise SystemExit(1)
    except (OSError,ValueError,KeyError) as error:raise SystemExit(f'Cannot verify v4 reset: {error}')
