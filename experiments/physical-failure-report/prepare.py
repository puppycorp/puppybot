#!/usr/bin/env python3
"""Build a separate opt-in simulated physical-peer failure reporter.

Usage: prepare.py NEW_OUTPUT_DIRECTORY
Copies the previously archived v3 source into a new directory; no GPU and no
changes to the archived build, live simulator, or live physical client.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
ARCHIVE=ROOT/'build/flex/sim/levels-v2/pitch82/physical-handoff-hint-build-v3/inputs/flex-source'
COMPILER=ROOT/'build/flex/control/compiler'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes(root):
    return {str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}


def once(text,old,new):
    if text.count(old)!=1:raise ValueError('unexpected client source shape')
    return text.replace(old,new,1)


HELPERS='''// Diagnostic only: an observed command echo is not physical motor feedback.
global pc_failure_enabled=0;
global pc_failure_armed=0;
global pc_failure_written=0;
global pc_explicit_stop=0;
fn pc_failure(reason,peer_zero) {
    if !pc_failure_enabled || !pc_failure_armed || pc_failure_written { return 0; }
    pc_failure_written=1; let b=alloc(32); let text=alloc(2048); pl_builder(b,text,2048);
    pl_text(b,"{\\"schema\\":\\"puppybot.sim-physical-failure.v1\\",\\"reason\\":"); pj_text(b,reason);
    pl_text(b,",\\"command\\":"); pl_int(b,pc_command_type); pl_text(b,",\\"sequence\\":"); pl_int(b,pc_sequence);
    pl_text(b,",\\"peerReportedZeroDrive\\":"); pj_bool_text(b,peer_zero);
    pl_text(b,",\\"stopCommandAcknowledged\\":"); pj_bool_text(b,pc_explicit_stop);
    pl_text(b,",\\"physicalStop\\":\\"unverified\\",\\"delivery\\":\\"unverified\\"}\\n");
    if load64(b+24) || pl_atomic_file(vc_path(pc_output,"failure.json"),text,load64(b+8)) { pl_print(2,"Cannot write diagnostic failure report.\\n"); }
    return 0;
}
fn pc_require(ok,message) {
    if !ok { pc_failure(message,0); } return vc_require(ok,message);
}
fn pc_json_int(root,a,b) {
    if !pc_failure_enabled { return vc_json_int(root,a,b); }
    let node=vc_json_path(root,a,b); pc_require(pj_kind(node)==1,"missing observation integer"); return pj_value(node);
}
fn pc_io(reading,fd,data,size) {
    if !pc_failure_enabled { return vc_io(reading,fd,data,size); }
    let at=0; let deadline=pl_now()+vc_io_timeout;
    while at<size {
        pc_require(pl_now()<deadline,"physical peer stream timeout");
        let n=0; if reading { n=syscall(0,fd,data+at,size-at,0,0,0); } else { n=syscall(44,fd,data+at,size-at,16384,0,0); }
        if n>0 { at=at+n; }
        else if n== -11 { let event=4; if reading { event=1; } pc_require(pl_wait(fd,event,deadline),"physical peer stream timeout or poll failure"); }
        else if n!= -4 { pc_require(0,"physical peer stream closed"); }
    } return 1;
}
'''


def transform(text):
    text=text.replace('vc_require(', 'pc_require(').replace('vc_json_int(', 'pc_json_int(').replace('vc_io(', 'pc_io(')
    text=once(text,'\nfn pc_observe() {','\n'+HELPERS+'\nfn pc_observe() {')
    text=once(text,'    pc_state = pj_parse(ve_json, size); pc_require(pc_state && pl_equal(pj_string_field(pc_state, "schema"), "puppybot.physical-agent.v1"), "invalid physical-agent schema");',
'''    pc_state = pj_parse(ve_json, size);
    if pc_failure_enabled {
        pc_require(pc_state,"invalid physical-agent schema"); let schema=pj_get(pc_state,"schema");
        pc_require(pj_kind(schema)==2,"invalid physical-agent schema"); pc_require(pl_equal(pj_value(schema),"puppybot.physical-agent.v1"),"invalid physical-agent schema");
    } else { pc_require(pc_state && pl_equal(pj_string_field(pc_state, "schema"), "puppybot.physical-agent.v1"), "invalid physical-agent schema"); }''')
    text=once(text,'    let simulator = load64(argv + 8);','''    value = pl_environment(argc, argv, "PUPPYBOT_SIM_FAILURE_REPORT");
    if value { pc_require(pl_equal(value,"0") || pl_equal(value,"1"),"invalid simulated failure report flag"); pc_failure_enabled=pl_equal(value,"1"); }
    let simulator = load64(argv + 8);''')
    text=once(text,'    pc_pin_inputs(simulator, model, case_path, environment); ve_policy_open(model, pc_output);',
              '    pc_pin_inputs(simulator, model, case_path, environment); pc_failure_armed=1; ve_policy_open(model, pc_output);')
    text=once(text,'    let ack = pc_command(3, 0, 0, 0); pc_require(ack == 7 && pc_json_int(pc_state, "owner", 0) == 2, "simulated stop request not acknowledged");',
              '    let ack = pc_command(3, 0, 0, 0); pc_require(ack == 7 && pc_json_int(pc_state, "owner", 0) == 2, "simulated stop request not acknowledged"); pc_explicit_stop=1;')
    text=once(text,'let ack = pc_command(7, 0, 0, 20); pc_require(ack == 4 || ack == 5, "collector stopped with a protocol or time-limit failure");',
              'let ack = pc_command(7, 0, 0, 20); if pc_failure_enabled && ack == 6 { pc_failure("collector peer reported failure",1); } pc_require(ack == 4 || ack == 5, "collector stopped with a protocol or time-limit failure");')
    return text


def prepare(output):
    output=Path(output).absolute();output.mkdir(parents=False,exist_ok=False)
    source=output/'flex';before=hashes(ARCHIVE);shutil.copytree(ARCHIVE,source,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    if hashes(source)!=before or hashes(ARCHIVE)!=before:raise ValueError('source archive changed while copying')
    compiler=digest(COMPILER);client=source/'control/physical-client.flex'
    subprocess.run([str(COMPILER),str(client),'-o',str(output/'baseline')],cwd=ROOT,check=True,timeout=120,capture_output=True)
    client.write_text(transform(client.read_text()));patched=hashes(source)
    if any(before[k]!=patched[k] for k in before if k!='control/physical-client.flex'):raise ValueError('unexpected source differences')
    subprocess.run([str(COMPILER),str(client),'-o',str(output/'candidate')],cwd=ROOT,check=True,timeout=120,capture_output=True)
    if digest(COMPILER)!=compiler or hashes(source)!=patched or hashes(ARCHIVE)!=before:raise ValueError('build inputs changed')
    report={'schema':'puppybot.sim-physical-failure-build.v1','compilerSHA256':compiler,'archiveSource':before,'candidateSource':patched,
            'baselineSHA256':digest(output/'baseline'),'candidateSHA256':digest(output/'candidate'),
            'scope':'simulated peer diagnostics only; no physical stop or delivery proof'}
    (output/'build.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');return report


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit(__doc__)
    report=prepare(sys.argv[1])
    print(json.dumps({'status':'isolated_build_only','candidateSHA256':report['candidateSHA256'],'scope':report['scope']}))
