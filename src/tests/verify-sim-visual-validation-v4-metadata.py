#!/usr/bin/env python3
"""Independently bind every v4 scene label and case field to frozen v3.

Usage: verify-sim-visual-validation-v4-metadata.py V3 V4 RESET_REPORT
Reads inputs only. The CPU reset report is consistency-checked; no rendered
startup, policy, physical task or hardware outcome is established.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def same(left,right):
    # Sorted JSON distinguishes bool from int and integer from float, unlike
    # Python's ordinary equality, while preserving nested arrays and fields.
    return json.dumps(left,sort_keys=True,allow_nan=False,separators=(',',':'))==json.dumps(right,sort_keys=True,allow_nan=False,separators=(',',':'))


def compare_rows(old_rows,new_rows):
    if not isinstance(old_rows,list) or not isinstance(new_rows,list):raise ValueError('invalid row lists')
    old={row['name']:row for row in old_rows};new={row['name']:row for row in new_rows}
    if len(old_rows)!=12 or len(new_rows)!=12 or len(old)!=12 or len(new)!=12 or old.keys()!=new.keys():raise ValueError('scene condition names differ')
    extra={'v3CaseSHA256','caseControllerChange','cpuParserPreflight'}
    for name,source in old.items():
        derived=new[name]
        if set(derived)!=set(source)|extra:raise ValueError('scene metadata keys differ: '+name)
        for key,value in source.items():
            if key=='caseSHA256' and name.startswith('room-'):continue
            if not same(value,derived[key]):raise ValueError('scene metadata differs: '+name+' '+key)
        expected='rgb-find-return -> rgb-discovery' if name.startswith('room-') else 'none'
        if derived['caseControllerChange']!=expected or derived['v3CaseSHA256']!=source['caseSHA256']:
            raise ValueError('scene controller metadata differs: '+name)
        check=derived['cpuParserPreflight']
        if not isinstance(check,dict) or check.get('accepted') is not True or type(check.get('returnCode')) is not int or check['returnCode']!=0:
            raise ValueError('missing successful parser check: '+name)
    return old,new


def audit(v3,v4,reset_report):
    v3=Path(v3).absolute();v4=Path(v4).absolute();reset_report=Path(reset_report).absolute()
    source=json.loads((v3/'conditions.json').read_text());plan=json.loads((v4/'conditions.json').read_text());reset=json.loads(reset_report.read_text())
    if (source.get('schema')!='puppybot.visual-stop-validation-inputs.v1' or plan.get('schema')!='puppybot.visual-stop-validation-plan.v4'
            or plan.get('status')!='cpu_parser_preflight_only' or plan.get('sourceV3')!=str(v3) or plan.get('sourceV3ManifestSHA256')!=sha(v3/'conditions.json')
            or reset.get('schema')!='puppybot.visual-stop-v4-reset-report.v1' or reset.get('status')!='all_cpu_resets_accepted'
            or reset.get('pilot')!=plan.get('pilot') or reset.get('v4')!=str(v4) or reset.get('v4ManifestSHA256')!=sha(v4/'conditions.json')):
        raise ValueError('plan/reset evidence identity differs')
    source_files={'casePreflightSHA256':ROOT/'flex/tests/physical-case-preflight.py',
                  'resetPreflightSHA256':ROOT/'flex/tests/physical-reset-preflight.py',
                  'verifierSHA256':ROOT/'flex/tests/verify-sim-visual-validation-v4-reset.py'}
    if any(reset.get(key)!=sha(path) for key,path in source_files.items()):raise ValueError('recorded reset source changed')
    if plan.get('preflightSHA256')!=sha(source_files['casePreflightSHA256']) or plan.get('planGeneratorSHA256')!=sha(ROOT/'flex/tests/prepare-sim-visual-validation-v4.py'):
        raise ValueError('recorded plan source changed')
    pilot=Path(plan['pilot']);pilot_receipt=json.loads((pilot/'inputs.json').read_text());asset=Path(pilot_receipt['paths']['asset'])
    if not asset.is_absolute() or pilot_receipt['files'].get(str(asset))!=sha(asset) or reset.get('assetSHA256')!=sha(asset):
        raise ValueError('recorded robot asset changed')
    source_rows,plan_rows=compare_rows(source['conditions'],plan['conditions'])
    checks={row['name']:row for row in reset.get('cases',[])}
    if len(reset.get('cases',[]))!=12 or set(checks)!=set(source_rows) or reset.get('accepted')!=12:raise ValueError('reset report incomplete')
    for name,old in source_rows.items():
        row=plan_rows[name];case=v4/name/'case.json';env=v4/name/'environment.bin';old_case=v3/name/'case.json';old_env=v3/name/'environment.bin'
        if (sha(old_case)!=old['caseSHA256'] or sha(old_env)!=old['environmentSHA256'] or sha(case)!=row['caseSHA256']
                or sha(env)!=row['environmentSHA256'] or env.read_bytes()!=old_env.read_bytes()):raise ValueError('scene file changed: '+name)
        before=json.loads(old_case.read_text());after=json.loads(case.read_text())
        if name.startswith('room-'):
            if before.get('controller')!='rgb-find-return' or after.get('controller')!='rgb-discovery':raise ValueError('wrong room controller: '+name)
            before['controller']='rgb-discovery'
            if not same(before,after):raise ValueError('room case differs beyond controller: '+name)
        elif case.read_bytes()!=old_case.read_bytes():raise ValueError('apartment case differs: '+name)
        check=checks[name]
        if (check.get('accepted') is not True or type(check.get('returnCode')) is not int or check['returnCode']!=0
                or check.get('caseSHA256')!=row['caseSHA256'] or check.get('environmentSHA256')!=row['environmentSHA256']):
            raise ValueError('reset case identity differs: '+name)
    return {'status':'metadata_consistent_cpu_reset_report_only','conditions':len(source_rows),
            'v3ManifestSHA256':sha(v3/'conditions.json'),'v4ManifestSHA256':sha(v4/'conditions.json'),'resetReportSHA256':sha(reset_report),
            'scope':'recorded CPU-only pre-render reset and scene metadata consistency; no rendered startup, policy, task result or hardware evidence'}


if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit(__doc__)
    try:print(json.dumps(audit(*sys.argv[1:]),sort_keys=True))
    except (OSError,ValueError,KeyError,TypeError) as error:raise SystemExit(f'Invalid v4 metadata: {error}')
