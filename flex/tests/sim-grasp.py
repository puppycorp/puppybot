#!/usr/bin/env python3
"""Physical regression for a folded floor grasp and collision-free loaded stow.

The target is an explicit calibration fixture, not a perception/end-to-end test.
All six house objects and the original robot/scene/servo limits are preserved.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def check(directory):
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn checked_tick() {
    if !ps_tick(0) || ps_arm_blocked || load64(ps_physics+192) {return 0;}
    if ps_gripper_held {
        // Judge only: these physical body queries never supply control targets.
        ph_cache_body(ph_body(ps_physics,ps_gripper_body));let a=ps_body_shape(ps_gripper_body);ph_cache_shape(ps_physics,a);
        ph_cache_body(ph_body(ps_physics,4));let b=ps_body_shape(4);ph_cache_shape(ps_physics,b);if ph_sat(a,b,ps_solid_scratch) {return 0;}
        let j=0;while j<ps_arm_collider_count {let id=ps_arm_proxy_body+j;ph_cache_body(ph_body(ps_physics,id));b=ps_body_shape(id);ph_cache_shape(ps_physics,b);if ph_sat(a,b,ps_solid_scratch) {return 0;}j=j+1;}
    }
    return 1;
}
fn settled() {let n=0;while n<1500 && !ps_pickup_settled() {if !checked_tick() {return 0;}n=n+1;}return n<1500;}
fn main(argc,argv) {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("house-blocks-into-box")) || !ps_model_load("build/flex/sim/puppybot.bin") || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") {return 1;}
    let centred=argc>2 && pl_equal(load64(argv+16),"centred");let spawn="[0.964,0.54,0]";if centred {spawn="[0.964,0.5,0]";}if !ps_environment_spawn(spawn) {return 1;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);
    pb_config_default(ps_config);ps_discovery_enabled=1;if !ps_reset() {return 2;}ps_discovery_phase=0;ps_collect_enabled=1;ps_collect_reset();ps_collect_busy=1;ps_gripper_auto=1;
    ps_output=syscall(2,load64(argv+8),0x800c1,384,0,0,0);if ps_output<0 {return 3;}
    let i=0;while i<100 {if !checked_tick() {return 4;}i=i+1;}
    let p=ps_case_target;store64(p,ps_number(186,1000));store64(p+8,ps_number(-4,100));store64(p+16,ps_number(12,1000));
    if centred {store64(p+8,0);}
    if (argc>2 && !centred) || argc>3 {store64(p,f64_add(load64(p),ps_number(1,1000)));store64(p+8,f64_sub(load64(p+8),ps_number(1,1000)));}
    if !ps_grasp_move(p,40,-30) || !settled() {return 5;}
    if !ps_grasp_move(p,0,-30) || !settled() {return 6;}
    ps_gripper_command(0);i=0;while i<300 && !ps_gripper_held {if !checked_tick() {return 7;}i=i+1;}
    if !ps_gripper_held || ps_gripper_witnesses!=3 {return 8;}
    if !ps_grasp_move(p,40,-30) || !settled() {return 9;}
    if !ps_collect_stow_begin() {return 10;}i=0;
    while i<5000 && ps_case_stage!=19 {if !checked_tick() || ps_case_stage==13 {return 11;}i=i+1;}
    if i==5000 {return 12;}ps_case_phase(0);if !settled() || !ps_gripper_held {return 13;}
    ps_observation();pl_print(1,ps_json);syscall(3,ps_output,0,0,0,0,0);return 0;
}
'''
    entry, binary = directory/'probe.flex', directory/'probe'
    entry.write_text(source)
    subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler')), str(entry), '-o', str(binary)], cwd=ROOT, check=True)
    for name, extra in [('nominal', []), ('perturbed', ['perturbed']), ('centred', ['centred']), ('centred-perturbed', ['centred','perturbed'])]:
        trace = directory/(name+'.jsonl')
        result = subprocess.run([str(binary), str(trace), *extra], cwd=ROOT, capture_output=True, text=True, timeout=60)
        (directory/(name+'.log')).write_text(result.stdout+result.stderr)
        assert result.returncode==0, (name,result.returncode,result.stderr)
        state=json.loads(result.stdout.splitlines()[-1]);gripper=state['gripper']
        assert gripper['held'] and gripper['captureContactMask']==3 and gripper['grasps']==1
        assert gripper['maxHeldBallHeight']>.3 and state['camera']['pose']=='driving'
        assert state['localization']['initialPrior']=='local-origin' and state['case']['required']==6
        print(name+': actual bilateral capture, stable lift, production staged stow and no chassis/arm intersection passed')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True,exist_ok=False);check(args.output)
    else:
        with tempfile.TemporaryDirectory(prefix='grasp-check-',dir=ROOT/'build/flex/sim') as temporary:check(Path(temporary))


if __name__=='__main__':main()
