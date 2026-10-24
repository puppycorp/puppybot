#!/usr/bin/env python3
"""Check that identical TCP pixels still detect a box in a shifted odometry frame."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main() {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("house-blocks-into-box")) || !ps_environment_load("build/flex/sim/environments/apartment/apartment.bin") || !ps_model_load("build/flex/sim/puppybot.bin") {return 1;}
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);
    pb_config_default(ps_config);pb_vset(ps_config+40,2,5);ps_local_requested=1;ps_previews=0;
    if !ps_reset() {return 2;}ps_render_init(1);if !ps_case_start(){return 3;}
    let steps=0;while steps<1500 && !ps_house_ready {if !ps_tick(0){return 4;}steps=steps+1;}
    if !ps_house_ready {return 5;}ps_case_phase(0);pb_drive_stop(pb_robot_drive(ps_robot),ps_time);
    if !ps_dock_sample() || !ps_dock_valid {return 6;}
    let x=load64(ps_dock_frame+96);let y=load64(ps_dock_frame+104);let pixels=alloc(640*480*3);pb_copy(pixels,ps_brick_rgb,640*480*3);
    ps_local_y=f64_add(ps_local_y,ps_number(4,10));
    if !ps_dock_sample() || !ps_dock_valid {return 7;}
    if !f64_gt(load64(ps_dock_frame+104),0) {return 8;}
    if f64_gt(f64_magnitude(f64_sub(load64(ps_dock_frame+96),x)),ps_number(3,1000)) || f64_gt(f64_magnitude(f64_sub(f64_sub(load64(ps_dock_frame+104),y),ps_number(4,10))),ps_number(3,1000)) {return 9;}
    let i=0;while i<640*480*3 {if load8(pixels+i)!=load8(ps_brick_rgb+i){return 10;}i=i+1;}
    let saved=alloc(128);pb_copy(saved,ps_dock_frame,128);ps_dock_count=2;ps_dock_valid=0;ps_dock_seen=-1;ps_dock_stable=0;ps_dock_hint_seen=-1;
    ps_dock_attention(0);if !ps_dock_hint_fresh() || ps_dock_fresh() || ps_dock_stable || ps_dock_seen!=-1 {return 11;}
    i=0;while i<16 {if load64(saved+i*8)!=load64(ps_dock_frame+i*8){return 12;}i=i+1;}
    pl_print(1,"Dock frame checks passed: identical RGB, positive-Y estimated box detected, 40 cm frame shift preserved, unchanged scene, partial attention never confirms a pose\n");
    ps_render_close();ph_world_close(ps_physics);ps_environment_close();return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='dock-frames-', dir=ROOT/'build/flex/sim') as temporary:
        directory = Path(temporary)
        entry, binary = directory/'probe.flex', directory/'probe'
        entry.write_text(source)
        compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler'))
        subprocess.run([compiler, str(entry), '-o', str(binary)], cwd=ROOT, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True, timeout=45)


if __name__ == '__main__':
    main()
