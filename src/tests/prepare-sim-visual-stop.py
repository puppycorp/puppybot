#!/usr/bin/env python3
"""Build a new isolated simulation-only visual stop prototype; no GPU work.

Usage: prepare-sim-visual-stop.py NEW_DIRECTORY
Both arms use this one binary. Enable by PUPPYBOT_SIM_VISUAL_STOP=1. The
client terminates after a reported stop; it does not maneuver or resume.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPILER = ROOT / 'build/flex/control/compiler'


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('source changed; hook anchor is not unique')
    return text.replace(old, new, 1)


def prepare(output):
    output.mkdir(parents=False, exist_ok=False)
    source = output / 'flex'; original = hashes(ROOT / 'flex')
    shutil.copytree(ROOT / 'flex', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if hashes(source) != original or hashes(ROOT / 'flex') != original:
        raise ValueError('source changed while snapshotting')
    module = source / 'control/sim-visual-stop.flex'
    if module.exists():
        raise ValueError('visual stop destination already exists')
    shutil.copyfile(source / 'tests/sim-visual-stop.flex', module)
    path = source / 'control/physical-client.flex'; text = path.read_text()
    text = replace_once(text, 'import "progress-guard.flex";', 'import "progress-guard.flex";\nimport "sim-visual-stop.flex";\nglobal pc_visual_enabled=0;\nglobal pc_visual_reason=0;')
    text = replace_once(text, '    let simulator = load64(argv + 8);', '''    value = pl_environment(argc, argv, "PUPPYBOT_SIM_VISUAL_STOP");
    if value { vc_require(pl_equal(value,"0") || pl_equal(value,"1"),"invalid simulator visual stop flag"); pc_visual_enabled=pl_equal(value,"1"); }
    if pc_visual_enabled { os_reset(); }
    let simulator = load64(argv + 8);''')
    text = replace_once(text, '    while actions < nav_limit && !handoff {', '''    while actions < nav_limit && !handoff && !pc_visual_reason {
        if pc_visual_enabled {
            let name=vc_concat("visual-",vc_int(pc_sequence));
            vc_write(vc_path(pc_actors,vc_concat(name,".rgb")),ve_image,ve_image_bytes);
            let speed=0; if pc_command_type==2 && pc_command_hold==10 { speed=pc_command_speed; }
            pc_visual_reason=os_observe(ve_image,vc_json_int(pc_state,"totalSteps",0),speed);
        }''')
    text = replace_once(text, '        if vc_json_int(pc_state, "rgbDetections", 0) > 0 {', '        if !pc_visual_reason && vc_json_int(pc_state, "rgbDetections", 0) > 0 {')
    text = replace_once(text, '        if !handoff {\n            pc_record_input();', '        if !handoff && !pc_visual_reason {\n            pc_record_input();')
    text = replace_once(text, '    if pc_rescan_enabled && !handoff && actions == nav_limit', '    if pc_rescan_enabled && !pc_visual_reason && !handoff && actions == nav_limit')
    text = replace_once(text, '    pl_text(b, ",\\"stopCommandAcknowledged\\":true,\\"outcome\\":\\"unverified\\",\\"traceSHA256\\":");', '''    pl_text(b, ",\\"visualStopEnabled\\":"); pj_bool_text(b,pc_visual_enabled);
    pl_text(b, ",\\"visualStopReason\\":"); pl_int(b,pc_visual_reason);
    pl_text(b, ",\\"stopCommandAcknowledged\\":true,\\"outcome\\":\\"unverified\\",\\"traceSHA256\\":");''')
    path.write_text(text)
    patched = hashes(source); compiler_sha = hashlib.sha256(COMPILER.read_bytes()).hexdigest()
    subprocess.run([str(COMPILER), str(path), '-o', str(output / 'client')], cwd=ROOT, check=True, timeout=120)
    if patched != hashes(source) or compiler_sha != hashlib.sha256(COMPILER.read_bytes()).hexdigest():
        raise ValueError('source or compiler changed while building')
    receipt = {'originalSource': original, 'patchedSource': patched, 'compilerSHA256': compiler_sha,
               'clientSHA256': hashlib.sha256((output / 'client').read_bytes()).hexdigest(),
               'scope': 'experimental simulated stop only; not hardware safety or obstruction proof'}
    (output / 'build.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    report = prepare(Path(sys.argv[1]).absolute())
    print(json.dumps({'clientSHA256': report['clientSHA256'], 'scope': report['scope']}, sort_keys=True))
