#!/usr/bin/env python3
"""Check external scene loading, rejection and the short simulator entry point."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def invoke(args, expected, directory, name):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=30)
    (directory/(name+'.log')).write_text(result.stdout+result.stderr)
    assert result.returncode == expected, (name, result.returncode, result.stdout, result.stderr)
    return result


def check(binary, directory, entry):
    catalog = ROOT/'flex/sim/cases/catalog.json'
    before = hashlib.sha256(catalog.read_bytes()).hexdigest()
    case = json.loads((ROOT/'flex/sim/cases/ball-into-bin.json').read_text())
    case.update(id='external-test-ball', controller='scene-state')
    path = directory/'case with spaces.json'
    path.write_text(json.dumps(case))
    args = [str(binary), '--headless', '--steps', '1', '--bind', '127.0.0.1:0']
    result = invoke([*args, '--case-file', str(path)], 1, directory, 'valid')
    state = json.loads(result.stdout.strip().splitlines()[-1])
    assert state['case']['id'] == case['id'] and state['case']['required'] == 1
    assert state['case']['phase'] != 'failed', 'step-budget exhaustion is not an invalid scene'
    invoke([*args, '--case-file', str(path), '--case', 'ball-into-bin'], 2, directory, 'conflict')
    invoke([*args, '--case-file', str(directory/'missing.json')], 2, directory, 'missing')
    for name, value in (('invalid-json', '{'), ('missing-fields', '{}'),
                        ('incomplete-case', json.dumps(dict(id='incomplete', controller='scene-state'))),
                        ('numeric-id', json.dumps(dict(case, id=42))),
                        ('numeric-controller', json.dumps(dict(case, controller=42))),
                        ('invalid-objects', json.dumps(dict(case, objects=42))),
                        ('unsupported-controller', json.dumps(dict(case, controller='unsupported'))),
                        ('duplicate-id', json.dumps(dict(case, id='ball-into-bin')))):
        invalid = directory/(name+'.json')
        invalid.write_text(value)
        invoke([*args, '--case-file', str(invalid)], 2, directory, name)
    if entry:
        result = invoke(['flexscript', 'run', 'sim.flex', '--case-file', str(path), '--headless', '--steps', '1'], 1, directory, 'entry')
        assert json.loads(result.stdout.strip().splitlines()[-1])['case']['id'] == case['id']
    assert hashlib.sha256(catalog.read_bytes()).hexdigest() == before
    (directory/'audit.json').write_text(json.dumps(dict(passed=True, externalCaseLoaded=True,
        invalidInputsRejected=True, catalogUnchanged=True, shortEntryChecked=entry), indent=2)+'\n')
    print('External cases passed: new scene without catalog edits, paths with spaces, conflicts/invalid input rejection'+', short entry selector' * entry, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, default=ROOT/'build/flex/puppybot-sim')
    parser.add_argument('--entry', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        check(args.binary.resolve(), args.output.resolve(), args.entry)
    else:
        with tempfile.TemporaryDirectory(prefix='case-file-', dir=ROOT/'build/flex/sim') as temporary:
            check(args.binary.resolve(), Path(temporary), args.entry)


if __name__ == '__main__':
    main()
