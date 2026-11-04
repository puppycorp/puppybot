#!/usr/bin/env python3
"""Build an isolated, opt-in simulator-only search handoff; no GPU launch."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
ARCHIVE=ROOT/'build/flex/sim/levels-v2/pitch82/physical-handoff-hint-build-v3'
COMPILER=ROOT/'build/flex/control/compiler'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashes(root):
    return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}


def once(text,old,new):
    if text.count(old)!=1:raise ValueError('unexpected archived source; refusing transform')
    return text.replace(old,new,1)


def gate(text):
    text=once(text,'fn ps_physical_sequence(previous, next)',
              'global ps_search_fallback_enabled = 0;\nfn ps_physical_sequence(previous, next)')
    return once(text,'    if command == 6 { return !owner; }',
                '    if command == 6 { return !owner; }\n    if command == 8 { return ps_search_fallback_enabled && !owner && !steering && !speed && !hold && task == 4; }')


SEARCH='''// Search-only transfer is not a target sighting, pickup or delivery.
fn ps_physical_search_only() {
    if !ps_search_fallback_enabled || !ps_agent_physical || ps_physical_owner || !ps_collect_enabled || !ps_discovery_enabled || ps_seek_enabled || !ps_local_mode || ps_agent_oracle || ps_nav_training_oracle { return ps_physical_halt(); }
    if !ps_physical_stop_before_handoff() || !ps_camera_drive_mode || !ps_camera_still() { return ps_physical_halt(); }
    if !ps_rgb_sample() || !ps_brick_detect() || ps_brick_frame != ps_total { return ps_physical_halt(); }
    // If a target appeared, retain navigation ownership for ordinary command 6.
    if ps_brick_count { ps_physical_ack = 2; return 1; }
    if !ps_collect_search_begin() { return ps_physical_halt(); }
    ps_physical_owner = 1; ps_physical_ticks = 0; ps_physical_ack = 8; return 1;
}
'''


def agent(text):
    text=once(text,'fn ps_physical_loop(video, capture) {',SEARCH+'fn ps_physical_loop(video, capture) {')
    return once(text,'        } else if initialized && command == 7 && ps_physical_owner == 1 {',
                '        } else if initialized && command == 8 && !ps_physical_owner {\n            if !ps_physical_search_only() { return ps_physical_abort(); } if !ps_physical_observe() { ps_physical_halt(); return 1; }\n        } else if initialized && command == 7 && ps_physical_owner == 1 {')


def main_sim(text):
    return once(text,'    if !pl_init() { return 1; } h_environment(argc, argv); gx_env = argv + (argc + 1) * 8;',
'''    if !pl_init() { return 1; } h_environment(argc, argv); gx_env = argv + (argc + 1) * 8;
    let search = pl_environment(argc, argv, "PUPPYBOT_PHYSICAL_SEARCH_FALLBACK");
    if search { if !pl_equal(search, "0") && !pl_equal(search, "1") { return 2; } ps_search_fallback_enabled = pl_equal(search, "1"); }''')


def sensor_gate(text):
    text=once(text,'    if command == 6 { return frame == previous + 2; }',
              '    if command == 6 || command == 8 { return frame == previous + 2; }')
    text=once(text,'    if command == 7 { return (owner == 1 && ack == 4) || (owner == 2 && (ack == 5 || ack == 6)); }',
              '    if command == 7 { return (owner == 1 && ack == 4) || (owner == 2 && (ack == 5 || ack == 6)); }\n    if command == 8 { return (!owner && ack == 2) || (owner == 1 && ack == 8); }')
    return once(text,'    if command == 1 || command == 3 || command == 6 || (command == 7 && (ack == 5 || ack == 6))',
                '    if command == 1 || command == 3 || command == 6 || command == 8 || (command == 7 && (ack == 5 || ack == 6))')


CLIENT_SEARCH='''// No target or floor estimate is supplied; this requests simulator search only.
fn pc_search_fallback() {
    let before = pc_last_frame; let ack = pc_command(8, 0, 0, 0);
    let now = vc_json_int(pc_state, "totalSteps", 0);
    vc_require(!pj_error && now == before + 2, "search transfer did not advance two stopped ticks");
    if ack == 8 {
        vc_require(pj_kind(pj_get(pc_state, "rgbDetections")) == 0 && vc_json_int(pc_state, "cameraFrame", 0) == -1 && !pj_boolean(pc_state, "cameraDriving") && !pj_boolean(pc_state, "cameraStill") && !pj_error, "invalid search-owned observation");
        let joints = pj_get(pc_state, "jointTicks"); vc_require(pj_kind(joints) == 3 && pj_count(joints) == 4, "missing search-transfer joints");
        let j = 0; while j < 4 { let node = pj_index(joints, j); vc_require(pj_kind(node) == 1 && pj_value(node) == load64(pc_arm + j * 8), "search-transfer arm changed"); j = j + 1; }
        let i = 0; while i < 640 * 480 * 3 { vc_require(!load8(ve_rgb + i), "search-owned frame must be blank"); i = i + 1; }
        pc_search_started = 1; return 0;
    }
    vc_require(ack == 2 && vc_json_int(pc_state, "rgbDetections", 0) > 0 && !pj_error, "search rejection lacks fresh target");
    before = pc_last_frame; ack = pc_command(6, 0, 0, 0); now = vc_json_int(pc_state, "totalSteps", 0);
    vc_require(!pj_error && now == before + 2 && (ack == 2 || ack == 3), "ordinary target handoff invalid after search request");
    return ack == 3;
}
'''


CLIENT_INTENT='''// This records client intent before send, not peer receipt or a stop proof.
fn pc_search_intent(command, steering, speed, hold) {
    let b = alloc(32); let text = alloc(512); pl_builder(b, text, 512);
    pl_text(b, "{\\"sequence\\":"); pl_int(b, pc_sequence); pl_text(b, ",\\"command\\":"); pl_int(b, command);
    pl_text(b, ",\\"steering\\":"); pl_int(b, steering); pl_text(b, ",\\"speed\\":"); pl_int(b, speed); pl_text(b, ",\\"hold\\":"); pl_int(b, hold); pl_text(b, "}\\n");
    vc_require(!load64(b + 24) && !pl_write(pc_search_requests, text, load64(b + 8)), "cannot write search request intent");
    syscall(11, b, 32, 0, 0, 0, 0); syscall(11, text, 512, 0, 0, 0, 0); return 1;
}
'''


def client(text):
    text=once(text,'global pc_rescan_stop_reason = 0;', 'global pc_rescan_stop_reason = 0;\nglobal pc_search_enabled = 0;\nglobal pc_search_started = 0;\nglobal pc_search_requests = -1;')
    text=once(text,'fn pc_command(command, steering, speed, hold) {',CLIENT_INTENT+'fn pc_command(command, steering, speed, hold) {')
    text=once(text,'    vc_io(0, load64(pc_process + 8), pc_request, 64); return pc_observe();',
              '    if pc_search_enabled { pc_search_intent(command, steering, speed, hold); }\n    vc_io(0, load64(pc_process + 8), pc_request, 64); return pc_observe();')
    text=once(text,'fn pc_pin_inputs(simulator, model, case_path, environment) {',CLIENT_SEARCH+'fn pc_pin_inputs(simulator, model, case_path, environment) {')
    text=once(text,'    pl_text(b, ",\\"stopCommandAcknowledged\\":true,\\"outcome\\":\\"unverified\\",\\"traceSHA256\\":");',
'''    if pc_search_enabled { pl_text(b, ",\\"searchFallbackStarted\\":"); pj_bool_text(b, pc_search_started); }
    pl_text(b, ",\\"stopCommandAcknowledged\\":true,\\"outcome\\":\\"unverified\\",\\"traceSHA256\\":");''')
    text=once(text,'    pj_bool_text(b, pc_rescan_enabled); pl_text(b, "}\\n");',
'''    pj_bool_text(b, pc_rescan_enabled); if pc_search_enabled { pl_text(b, ",\\"searchFallbackEnabled\\":true"); } pl_text(b, "}\\n");''')
    text=once(text,'    let simulator = load64(argv + 8); let model = load64(argv + 16);',
'''    value = pl_environment(argc, argv, "PUPPYBOT_PHYSICAL_SEARCH_FALLBACK");
    if value { vc_require(pl_equal(value, "0") || pl_equal(value, "1"), "invalid search fallback opt-in"); pc_search_enabled = pl_equal(value, "1"); }
    vc_require(!(pc_rescan_enabled && pc_search_enabled), "search fallback and guarded rescan cannot both be enabled");
    let simulator = load64(argv + 8); let model = load64(argv + 16);''')
    text=once(text,'    let polls = 0; let terminal = 0;\n    while handoff && polls < poll_limit && !terminal',
'''    if pc_search_enabled && !handoff && actions == nav_limit {
        // Give a target in the last actor frame the ordinary detection path.
        let detections = vc_json_int(pc_state, "rgbDetections", 0); vc_require(detections >= 0, "invalid search observation detection count");
        if detections > 0 {
            let before = pc_last_frame; let ack = pc_command(6, 0, 0, 0); let now = vc_json_int(pc_state, "totalSteps", 0);
            vc_require(!pj_error && now == before + 2 && (ack == 2 || ack == 3), "ordinary target handoff invalid at navigation limit");
            if ack == 3 { handoff = 1; }
        }
        if !handoff { handoff = pc_search_fallback(); }
    }
    let polls = 0; let terminal = 0;
    while (handoff || pc_search_started) && polls < poll_limit && !terminal''')
    text=once(text,'    pc_pin_inputs(simulator, model, case_path, environment); ve_policy_open(model, pc_output);',
'''    if pc_search_enabled { pc_search_requests = syscall(2, vc_path(pc_output, "search-requests.jsonl"), 0x800c1, 384, 0, 0, 0); vc_require(pc_search_requests >= 0, "cannot create search request intent journal"); }
    pc_pin_inputs(simulator, model, case_path, environment); ve_policy_open(model, pc_output);''')
    text=once(text,'    syscall(3, pc_journal, 0, 0, 0, 0, 0); pl_print(1, "Hybrid run ended;',
              '    if pc_search_enabled { syscall(3, pc_search_requests, 0, 0, 0, 0, 0); }\n    syscall(3, pc_journal, 0, 0, 0, 0, 0); pl_print(1, "Hybrid run ended;')
    return text


def build(output):
    output=Path(output).absolute();output.mkdir(parents=False,exist_ok=False)
    report_path=ARCHIVE/'build.json';report_hash=sha(report_path);original=json.loads(report_path.read_text());archive=ARCHIVE/'inputs/flex-source';library=ARCHIVE/'inputs/build/flex/sim/library'
    if original.get('schema')!='puppybot.physical-handoff-hint-build.v1':raise ValueError('unexpected archived build receipt')
    baseline={name:original[key] for name,key in (('client','clientSHA256'),('simulator','baselineSimulatorSHA256'))}
    if sha(COMPILER)!=original['compilerSHA256'] or any(sha(ARCHIVE/'inputs'/name)!=digest for name,digest in baseline.items()):raise ValueError('archived compiler or baseline binary changed')
    if hashes(archive)!=original['patchedSource'] or hashes(library)!=original['library']:raise ValueError('archived inputs changed')
    source=output/'source';shutil.copytree(archive,source,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('agent.flex','collect.flex','main.flex'):shutil.copyfile(ARCHIVE/'original-source'/name,source/'sim'/name)
    if hashes(source)!=original['originalSource']:raise ValueError('original archived source differs')
    lib=output/'build/flex/sim/library';lib.parent.mkdir(parents=True);shutil.copytree(library,lib)
    if hashes(lib)!=original['library'] or hashes(library)!=original['library']:raise ValueError('simulator library changed while copying')
    adapter=lib/'lib/f64.flex';text=adapter.read_text();old=f'import "{archive / "core/words.flex"}";';new=f'import "{source / "core/words.flex"}";'
    adapter.write_text(once(text,old,new))
    (lib.parent/'dependencies.flex').write_text(f'import "{lib / "libs/render.flex"}";\nimport "{lib / "libs/physics/physics.flex"}";\n')
    for name,digest in baseline.items():
        src=ARCHIVE/'inputs'/name;target=output/('baseline-'+name);shutil.copyfile(src,target);target.chmod(0o755)
        if sha(src)!=digest or sha(target)!=digest:raise ValueError('baseline changed while copying')
    changes={'sim/physical-agent-gate.flex':gate,'sim/agent.flex':agent,'sim/main.flex':main_sim,
             'control/physical-sensor-gate.flex':sensor_gate,'control/physical-client.flex':client}
    for name,fn in changes.items():
        p=source/name;p.write_text(fn(p.read_text()))
    patched=hashes(source);libhash=hashes(lib);compiler=sha(COMPILER)
    if set(patched)!=set(original['originalSource']) or any(patched[k]!=original['originalSource'][k] for k in patched if k not in changes):raise ValueError('unexpected candidate source changes')
    for name,target in (('control/physical-client.flex','client'),('sim/main.flex','simulator')):
        subprocess.run([str(COMPILER),str(source/name),'-o',str(output/target)],cwd=ROOT,check=True,timeout=120,capture_output=True)
    if (hashes(source)!=patched or hashes(lib)!=libhash or sha(COMPILER)!=compiler or sha(report_path)!=report_hash or
            hashes(archive)!=original['patchedSource'] or hashes(library)!=original['library'] or
            any(sha(ARCHIVE/'inputs'/name)!=digest or sha(output/('baseline-'+name))!=digest for name,digest in baseline.items())):raise ValueError('build inputs changed')
    result={'schema':'puppybot.physical-search-fallback-build.v1','originalSource':original['originalSource'],'patchedSource':patched,
            'library':libhash,'compilerSHA256':compiler,'baselineClientSHA256':sha(output/'baseline-client'),
            'baselineSimulatorSHA256':sha(output/'baseline-simulator'),'clientSHA256':sha(output/'client'),'simulatorSHA256':sha(output/'simulator'),
            'scope':'isolated simulator-only search request; no physical stop, pickup or delivery proof'}
    (output/'build.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');return result


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    result=build(sys.argv[1]);print(json.dumps({'status':'isolated_build_only','clientSHA256':result['clientSHA256'],'simulatorSHA256':result['simulatorSHA256']}))
