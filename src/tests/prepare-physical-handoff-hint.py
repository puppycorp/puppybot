#!/usr/bin/env python3
"""Build an isolated, opt-in RGB handoff-hint simulator prototype.

Usage: prepare-physical-handoff-hint.py NEW_OUTPUT_DIRECTORY
Copies and builds source in NEW_OUTPUT only; starts no simulator or GPU job.
PUPPYBOT_PHYSICAL_HANDOFF_HINT=1 enables one bounded hint. No physical-hardware
safety or pickup result is claimed.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('rescan',ROOT/'flex/tests/run-physical-rescan-trial.py')
rescan=importlib.util.module_from_spec(spec);spec.loader.exec_module(rescan)


def once(text,old,new):
    if text.count(old)!=1:raise ValueError('unexpected source shape; refusing isolated transformation')
    return text.replace(old,new,1)


OLD_SIGHTING='''            let found = -1; let j = 0;
            while j < ps_collect_count { let p = ps_collect_points + j * 64;
                if load64(p + 24) == load64(r + 64) && ps_floor_near(load64(r + 32), load64(r + 40), p, ps_number(6, 100)) { found = j; } j = j + 1;
            }
            if found < 0 && ps_collect_count < 64 { found = ps_collect_count; ps_collect_count = ps_collect_count + 1; pb_zero(ps_collect_points + found * 64, 64); }
            if found >= 0 { let p = ps_collect_points + found * 64;
                if load64(p + 40) != ps_total { pb_copy(p, r + 32, 24); store64(p + 24, load64(r + 64)); store64(p + 32, load64(p + 32) + 1); store64(p + 40, ps_total); }
                if load64(p + 32) < 3 && !load64(p + 48) { hold = 1; }
            }
'''

HELPERS='''// One unconfirmed image-derived hint; never a clearance or pickup decision.
// It expires at the first later fresh collector observation, and after at
// most 500 simulated ticks. Coordinates come only from ps_brick_records.
fn ps_handoff_hint_capture() {
    ps_handoff_hint_valid = 0;
    if !ps_handoff_hint_enabled || !ps_agent_physical || ps_physical_owner != 0 || !ps_collect_enabled || ps_seek_enabled || !ps_local_mode || !ps_camera_drive_mode || !ps_camera_still() || ps_brick_frame != ps_total || ps_brick_count < 1 { return 0; }
    let i = 0; while i < ps_brick_count { let r = ps_brick_records + i * 128;
        let dx = f64_sub(load64(r + 32), ps_pose_x()); let dy = f64_sub(load64(r + 40), ps_pose_y());
        if f64_lt(f64_add(f64_mul(dx,dx),f64_mul(dy,dy)), f64_from_i64(4)) && ps_house_detection(i) {
            if !ps_handoff_hint { ps_handoff_hint = alloc(40); }
            pb_copy(ps_handoff_hint, r + 32, 24); store64(ps_handoff_hint + 24, load64(r + 64)); store64(ps_handoff_hint + 32, ps_total);
            ps_handoff_hint_valid = 1; ps_handoff_hint_captures = ps_handoff_hint_captures + 1; return 1;
        } i = i + 1;
    } return 0;
}
fn ps_handoff_hint_take(r) {
    if !ps_handoff_hint_valid || !ps_handoff_hint_enabled || !ps_agent_physical || ps_physical_owner != 1 || !ps_collect_enabled || ps_seek_enabled || !ps_local_mode || ps_brick_frame != ps_total || ps_total <= load64(ps_handoff_hint + 32) || ps_total - load64(ps_handoff_hint + 32) > 500 || ps_collect_count >= 64 { return -1; }
    if load64(r + 64) != load64(ps_handoff_hint + 24) || !ps_floor_near(load64(r + 32), load64(r + 40), ps_handoff_hint, ps_number(6,100)) { return -1; }
    let found = ps_collect_count; ps_collect_count = ps_collect_count + 1; let p = ps_collect_points + found * 64; pb_zero(p,64);
    pb_copy(p, ps_handoff_hint, 24); store64(p + 24,load64(ps_handoff_hint + 24)); store64(p + 32,1); store64(p + 40,load64(ps_handoff_hint + 32));
    ps_handoff_hint_valid = 0; ps_handoff_hint_uses = ps_handoff_hint_uses + 1; return found;
}
fn ps_collect_sighting(r) {
    let found = -1; let j = 0;
    while j < ps_collect_count { let p = ps_collect_points + j * 64;
        if load64(p + 24) == load64(r + 64) && ps_floor_near(load64(r + 32), load64(r + 40), p, ps_number(6, 100)) { found = j; } j = j + 1;
    }
    if found < 0 { found = ps_handoff_hint_take(r); }
    if found < 0 && ps_collect_count < 64 { found = ps_collect_count; ps_collect_count = ps_collect_count + 1; pb_zero(ps_collect_points + found * 64, 64); }
    if found >= 0 { let p = ps_collect_points + found * 64;
        if load64(p + 40) != ps_total { pb_copy(p, r + 32, 24); store64(p + 24, load64(r + 64)); store64(p + 32, load64(p + 32) + 1); store64(p + 40, ps_total); }
        if load64(p + 32) < 3 && !load64(p + 48) { return 1; }
    } return 0;
}
fn ps_handoff_hint_finish_observation() {
    if ps_handoff_hint_valid && ps_brick_frame == ps_total && ps_total > load64(ps_handoff_hint + 32) { ps_handoff_hint_valid = 0; } return 0;
}
'''


def transform_collect(text):
    text=once(text,'global ps_collect_restow = 0;', '''global ps_collect_restow = 0;
global ps_handoff_hint_enabled = 0;
global ps_handoff_hint_valid = 0;
global ps_handoff_hint = 0;
global ps_handoff_hint_captures = 0;
global ps_handoff_hint_uses = 0;''')
    text=once(text,'    ps_collect_restow = 0;\n    if !ps_collect_resume_goal', '    ps_collect_restow = 0; ps_handoff_hint_valid = 0; ps_handoff_hint_captures = 0; ps_handoff_hint_uses = 0;\n    if !ps_collect_resume_goal')
    text=once(text,'fn ps_collect_observe() {',HELPERS+'fn ps_collect_observe() {')
    text=once(text,OLD_SIGHTING,'            if ps_collect_sighting(r) { hold = 1; }\n')
    text=once(text,'    return hold;\n}\nfn ps_collect_travel_observe()', '    ps_handoff_hint_finish_observation(); return hold;\n}\nfn ps_collect_travel_observe()')
    return text


def transform_agent(text):
    return once(text,'    if !ps_collect_search_begin() { return ps_physical_halt(); }\n    ps_physical_owner = 1;',
                '    if !ps_collect_search_begin() { return ps_physical_halt(); }\n    ps_handoff_hint_capture();\n    ps_physical_owner = 1;')


def transform_main(text):
    text=once(text,'    if !pl_init() { return 1; } h_environment(argc, argv); gx_env = argv + (argc + 1) * 8;',
'''    if !pl_init() { return 1; } h_environment(argc, argv); gx_env = argv + (argc + 1) * 8;
    let handoff_hint = pl_environment(argc, argv, "PUPPYBOT_PHYSICAL_HANDOFF_HINT");
    if handoff_hint { if !pl_equal(handoff_hint,"0") && !pl_equal(handoff_hint,"1") { return 2; } ps_handoff_hint_enabled=pl_equal(handoff_hint,"1"); }''')
    return once(text,'ps_serial_observation(b); ps_agent_oracle_state(b); pl_text(b, ",\\"controller\\":");',
'''ps_serial_observation(b); ps_agent_oracle_state(b);
    if ps_agent_physical && ps_handoff_hint_enabled && ps_output >= 0 { pl_text(b, ",\\"handoffHint\\":{\\"captures\\":"); pl_int(b, ps_handoff_hint_captures); pl_text(b, ",\\"uses\\":"); pl_int(b, ps_handoff_hint_uses); pl_char(b,125); }
    pl_text(b, ",\\"controller\\":");''')


def dependencies_text(inputs):
    library=inputs/'build/flex/sim/library'
    return f'import "{library/"libs/render.flex"}";\nimport "{library/"libs/physics/physics.flex"}";\n'


def verify(output,report):
    output=Path(output);source=output/'inputs/flex-source';original=report['originalSource'];patched=report['patchedSource']
    if rescan.supervisor.source_hashes(source)!=patched:raise ValueError('isolated candidate source changed')
    if rescan.supervisor.source_hashes(output/'inputs/build/flex/sim/library')!=report['library']:raise ValueError('isolated simulator dependency changed')
    dependencies=output/'inputs/build/flex/sim/dependencies.flex'
    if dependencies.read_text()!=dependencies_text(output/'inputs') or rescan.sha(dependencies)!=report['dependenciesSHA256']:raise ValueError('isolated dependency imports changed')
    changes={'sim/collect.flex':transform_collect,'sim/agent.flex':transform_agent,'sim/main.flex':transform_main}
    if set(original)!=set(patched) or any(original[name]!=patched[name] for name in original if name not in changes):raise ValueError('unexpected source changes beyond hint')
    for name,transform in changes.items():
        saved=output/'original-source'/Path(name).name
        if rescan.sha(saved)!=original[name] or (source/name).read_text()!=transform(saved.read_text()):raise ValueError('isolated source differs from reviewed hint transform')
    for path,key in ((rescan.COMPILER,'compilerSHA256'),(output/'inputs/simulator','baselineSimulatorSHA256'),(output/'simulator-hint','candidateSimulatorSHA256'),(output/'inputs/client','clientSHA256')):
        if rescan.sha(path)!=report[key]:raise ValueError('compiler or simulator changed: '+str(path))
    return True


def prepare(output):
    output=Path(output).absolute();output.mkdir(parents=False,exist_ok=False);inputs=output/'inputs';inputs.mkdir()
    original,library,compiler=rescan.build_snapshot(inputs);source=inputs/'flex-source';backup=output/'original-source';backup.mkdir()
    dependencies=inputs/'build/flex/sim/dependencies.flex'
    if dependencies.read_text()!=dependencies_text(inputs):raise ValueError('unexpected isolated dependency imports')
    dependency_hash=rescan.sha(dependencies)
    for name,fn in (('collect.flex',transform_collect),('agent.flex',transform_agent),('main.flex',transform_main)):
        path=source/'sim'/name;text=path.read_text();(backup/name).write_text(text);path.write_text(fn(text))
    patched=rescan.supervisor.source_hashes(source);candidate=output/'simulator-hint'
    subprocess.run([str(rescan.COMPILER),str(source/'sim/main.flex'),'-o',str(candidate)],cwd=ROOT,check=True,timeout=120,capture_output=True)
    if (rescan.sha(rescan.COMPILER)!=compiler or rescan.supervisor.source_hashes(source)!=patched
            or rescan.supervisor.source_hashes(inputs/'build/flex/sim/library')!=library or rescan.sha(dependencies)!=dependency_hash):raise ValueError('archived build inputs changed')
    report={'schema':'puppybot.physical-handoff-hint-build.v1','compilerSHA256':compiler,'baselineSimulatorSHA256':rescan.sha(inputs/'simulator'),
            'candidateSimulatorSHA256':rescan.sha(candidate),'clientSHA256':rescan.sha(inputs/'client'),'originalSource':original,'patchedSource':patched,'library':library,'dependenciesSHA256':dependency_hash,
            'hintMaxAgeTicks':500,'scope':'isolated opt-in RGB hint; no floor/clearance or physical-hardware proof'}
    verify(output,report)
    (output/'build.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');return report


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    report=prepare(sys.argv[1]);print(json.dumps({'status':'isolated_build_only','candidateSHA256':report['candidateSimulatorSHA256'],'scope':report['scope']}))
