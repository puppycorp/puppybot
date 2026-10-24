#!/usr/bin/env python3
"""Run the native case catalog and save a report for each physical outcome."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT/'build/flex/puppybot-sim'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', action='append', dest='cases', help='case ID; repeat to select several (default: all)')
    parser.add_argument('--seed', type=int, default=42, help='repeatable random floor layout (default: 42)')
    parser.add_argument('--steps', type=int, help='step budget (default: 24000; house: 150000)')
    parser.add_argument('--render', action='store_true', help='also save a native PNG of each outcome')
    parser.add_argument('--record', action='store_true', help='keep complete JSONL observations')
    parser.add_argument('--include-stress', action='store_true', help='include experimental challenges that can fail')
    parser.add_argument('--include-long', action='store_true', help='include room-to-room collection cases')
    parser.add_argument('--output', type=Path, help='new result directory')
    args = parser.parse_args()
    if not 0 <= args.seed <= 4294967295:
        parser.error('--seed must be between 0 and 4294967295')
    if args.steps is not None and not 1 <= args.steps <= 1000000:
        parser.error('--steps must be between 1 and 1000000')
    catalog_path = ROOT/'flex/sim/cases/catalog.json'
    catalog = json.loads(catalog_path.read_text())
    entries = {entry['id']: entry for entry in catalog['cases']}
    selected = args.cases or [case for case, entry in entries.items() if (args.include_stress or not entry.get('stress')) and (args.include_long or not entry.get('longRunning'))]
    if len(set(selected)) != len(selected) or any(case not in entries for case in selected):
        parser.error('case IDs must be unique and present in the catalog')
    output = args.output or ROOT/'build/flex/sim/cases'/f'run-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}'
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'puppybot.case-run.v1', 'catalogSha256': hashlib.sha256(catalog_path.read_bytes()).hexdigest(), 'cases': []}
    for case in selected:
        directory = output/case
        directory.mkdir()
        camera = entries[case]['controller'] in ('rgb-search', 'rgb-house')
        long = entries[case].get('longRunning', False)
        command = [str(BINARY), '--hidden' if args.render or camera else '--headless', '--steps', str(args.steps or (150000 if long else 24000)), '--case', case, '--seed', str(args.seed), '--bind', '127.0.0.1:0']
        if long:
            command += ['--until-done']
        if args.record:
            command += ['--record', str((directory/'observations.jsonl').resolve())]
        if args.render:
            command += ['--capture', str((directory/'outcome.png').resolve())]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=1800 if long else 480)
        (directory/'stdout.log').write_text(result.stdout)
        (directory/'stderr.log').write_text(result.stderr)
        state = json.loads(result.stdout.strip().splitlines()[-1])
        (directory/'state.json').write_text(json.dumps(state, indent=2)+'\n')
        outcome = state['case']
        passed = result.returncode == 0 and outcome['passed'] and outcome['inside'] == outcome['required'] and not state['gripper']['held'] and state['physicsFault'] == 0
        definition = ROOT/entries[case]['file']
        item = {'id': case, 'passed': passed, 'reason': outcome['reason'], 'placed': outcome['placed'], 'inside': outcome['inside'], 'required': outcome['required'],
                'controller': outcome['controller'], 'seed': outcome['seed'], 'returnCode': result.returncode, 'definitionSha256': hashlib.sha256(definition.read_bytes()).hexdigest()}
        report['cases'].append(item)
        print(f'{case}: {"PASS" if passed else "FAIL"} ({outcome["inside"]}/{outcome["required"]} inside)', flush=True)
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(output/'report.json')
    return 0 if all(item['passed'] for item in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
