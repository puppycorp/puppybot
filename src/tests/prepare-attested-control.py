#!/usr/bin/env python3
"""Build an isolated chase control with native actor and argv recording.

Usage: python3 -I flex/tests/prepare-attested-control.py NEW_BUILD_DIRECTORY
The output is experimental and must not replace the active control binary.
The captured bytes attest neither the kernel/runtime identity nor that a
malicious owner could not alter files. No GPU or simulator is started here.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPILER = ROOT / 'build/flex/control/compiler'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(path, before, after):
    text = path.read_text()
    if text.count(before) != 1:
        raise ValueError(f'expected exactly one hook location in {path}')
    path.write_text(text.replace(before, after, 1))


def prepare(output):
    output.mkdir(parents=False, exist_ok=False)
    source = output / 'flex'
    original = {str(p.relative_to(ROOT / 'flex')): digest(p)
                for p in sorted((ROOT / 'flex').rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    shutil.copytree(ROOT / 'flex', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    copied = {str(p.relative_to(source)): digest(p) for p in sorted(source.rglob('*')) if p.is_file()}
    current = {str(p.relative_to(ROOT / 'flex')): digest(p)
               for p in sorted((ROOT / 'flex').rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    if original != copied or original != current:
        raise ValueError('source changed while snapshotting')
    host = source / 'control/host.flex'
    chase = source / 'control/chase.flex'
    main = source / 'control/main.flex'
    helpers = '''fn ax_write(value) {let word=alloc(8);store64(word,value);vc_require(!pl_write(ax_fd,word,8),"cannot write argv journal");syscall(11,word,8,0,0,0,0);return 0;}
fn ax_record(kind,count,argv) {
    vc_require(ax_fd>=0 && count>=1 && count<=128,"invalid argv journal record");ax_write(kind);ax_write(count);let i=0;
    while i<count {let arg=load64(argv+i*8);let size=pl_size(arg);ax_write(size);vc_require(!pl_write(ax_fd,arg,size),"cannot write argv bytes");i=i+1;}return 0;
}
fn ax_open(path) {
    ax_fd=syscall(2,path,0x800c1,384,0,0,0);vc_require(ax_fd>=0,"argv journal output must be new");
    vc_require(!pl_write(ax_fd,"PBARGV01",8),"cannot write argv journal header");ax_record(0,ax_argc,ax_argv);return 0;
}
fn ax_close() {vc_require(ax_fd>=0,"argv journal is not open");ax_write(2);ax_write(0);vc_require(!syscall(3,ax_fd,0,0,0,0,0),"cannot close argv journal");ax_fd=-1;return 0;}
'''
    replace_once(host, 'global vc_env=0;\n', 'global vc_env=0;\nglobal ax_fd=-1;\nglobal ax_argc=0;\nglobal ax_argv=0;\n')
    replace_once(host, 'fn vc_require(ok,message)', helpers + 'fn vc_require(ok,message)')
    replace_once(host, 'fn vc_spawn(args,log_path,directory,channel) {\n',
                 'fn vc_spawn(args,log_path,directory,channel) {\n    if ax_fd>=0 {ax_record(1,load64(args),args+8);}\n')
    replace_once(main, '    vc_init(argc,argv);if argc<2',
                 '    vc_init(argc,argv);ax_argc=argc;ax_argv=argv;if argc<2')
    replace_once(main, '    ve_open_buffers();if vw_chase && pl_equal(command,"collect")',
                 '    vc_require(vw_chase && vw_fetch && pl_equal(command,"run"),"attested build supports only fetch chase run");ve_open_buffers();if vw_chase && pl_equal(command,"collect")')
    replace_once(chase, 'import "actions.flex";\n', 'import "actions.flex";\nimport "actor-attestation.flex";\n')
    replace_once(chase, '    vc_mkdir(vw_output);let checksum=0;let mode=2;',
                 '    vc_mkdir(vw_output);vc_require(vw_fetch && vw_policy && !vw_chase_forward && !vw_ensemble_count && !vw_sample_actions && !vw_straight_bias && !vw_action_noise && !vw_search_cue && !vw_hide_carry && !vw_blackout && !ve_policy_raw,"attested build supports only unmodified single-policy fetch");ax_open(vc_path(vw_output,"argv.bin"));let checksum=0;let mode=2;')
    replace_once(chase, 'if vw_fetch {vx_place_fetch("start");}else {vx_place("start");}let action=alloc(8);let label=alloc(8);',
                 'if vw_fetch {vx_place_fetch("start");}else {vx_place("start");}let attestation=pa_open(vc_path(directory,"actor-attestation.bin"),seed,vw_horizon,ve_image_bytes,ve_memory_width);let action=alloc(8);let label=alloc(8);')
    replace_once(chase, '        if ve_contact {vx_contacts=vx_contacts+1;}vx_track(action);ve_step(action);',
                 '        pa_record(attestation,ve_steps,ve_sequence,vc_json_int(ve_state,"totalSteps",0),ve_image,ve_policy_input,ve_policy_output,action);\n        if ve_contact {vx_contacts=vx_contacts+1;}vx_track(action);ve_step(action);')
    replace_once(chase, '    syscall(3,vx_log,0,0,0,0,0);if vw_record_memory',
                 '    pa_finish(attestation);syscall(3,vx_log,0,0,0,0,0);if vw_record_memory')
    replace_once(chase, '    pl_char(b,93);if mode==1 {vc_finish(ve_policy,15000);',
                 '    pl_char(b,93);ax_close();if mode==1 {vc_finish(ve_policy,15000);')
    before = {str(p.relative_to(source)): digest(p) for p in sorted(source.rglob('*')) if p.is_file()}
    compiler_hash = digest(COMPILER)
    binary = output / 'control-attested'
    subprocess.run([str(COMPILER), str(source / 'control/main.flex'), '-o', str(binary)],
                   cwd=ROOT, check=True, timeout=120)
    after = {str(p.relative_to(source)): digest(p) for p in sorted(source.rglob('*')) if p.is_file()}
    if before != after or compiler_hash != digest(COMPILER):
        raise ValueError('compiler or source snapshot changed during build')
    report = {'schema': 'puppybot.attested-control-build.v1', 'compilerSHA256': compiler_hash,
              'binarySHA256': digest(binary), 'originalSourceSHA256': original, 'sourceSHA256': before,
              'scope': 'experimental snapshot; records actor buffers and intended child exec argv, not loaded runtime identity or tamper-proof process attestation'}
    (output / 'build.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    return report


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(json.dumps(prepare(Path(sys.argv[1]).absolute()), sort_keys=True))


if __name__ == '__main__':
    main()
