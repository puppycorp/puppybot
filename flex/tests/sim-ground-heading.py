#!/usr/bin/env python3
"""Check RGB floor-line heading with biased priors and corrupted simulator truth."""
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def main():
    with tempfile.TemporaryDirectory(prefix='ground-heading-', dir=ROOT/'build/flex/sim') as temporary:
        directory = Path(temporary)
        spec = importlib.util.spec_from_file_location('tcp_camera', Path(__file__).with_name('sim-tcp-camera.py'))
        camera = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(camera)
        binary = camera.native(directory)
        fixtures = [('home', [.18, 0, 0], False), ('turned', [.21, -.04, .02], False), ('loaded', [0, 0, 0], True), ('living-turn', [1.8, .7, 2.6], False), ('dining-turn', [5.4, .6, .8], False), ('opposite', [1.8, .7, math.pi], False), ('right-angle', [5.4, .6, math.pi/2], False), ('ambiguous', [2.3, -.8, -1.8], False)]
        calls = []
        for name, pose, held in fixtures:
            result = camera.capture(binary, directory/name, pose, held)
            base = result['basePose']
            c, s = math.cos(base[2]), math.sin(base[2])
            values = []
            for i in range(4):
                x, y, z = result['estimatedCamera'][i*3:i*3+3]
                if i == 0:
                    x, y = x-base[0], y-base[1]
                values.extend(round(v*1e6) for v in (c*x+s*y, c*y-s*x, z))
            (directory/(name+'.bin')).write_bytes(struct.pack('<12q', *values))
            with Image.open(directory/(name+'.png')) as image:
                (directory/(name+'.rgb')).write_bytes(image.convert('RGB').tobytes())
            calls.append('if check('+json.dumps(str(directory/name))+',ps_number('+str(round(base[2]*1000000))+',1000000),'+str(int(name in ('home', 'turned', 'loaded', 'opposite', 'right-angle')))+') {return '+str(len(calls)+1)+';}')
        source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
        source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
        source += r'''
fn check(prefix, expected, positive) {
    let rgb=alloc(640*480*3);pl_read_file(h_cat(prefix,".rgb"),rgb,640*480*3);pl_read_file(h_cat(prefix,".bin"),ps_cf_camera,96);
    ps_cf_extract(rgb,0,ps_cf_points);let valid=ps_ground_heading_read();let text=alloc(1024);let b=alloc(32);pl_builder(b,text,1024);pj_text(b,prefix);pl_text(b," confidence=");pl_float(b,ps_ground_confidence);pl_text(b," localAxis=");pl_float(b,ps_ground_heading);pl_text(b," expected=");pl_float(b,expected);pl_char(b,10);pl_print(1,text);if positive != valid {return 1;}
    if valid {
        let observed=pb_neg(ps_ground_heading);let prior=f64_add(expected,ps_number(12,100));
        let quadrant=f64_to_i64_nearest(f64_div(f64_sub(prior,observed),PB_HALF_PI));observed=f64_add(observed,f64_mul(f64_from_i64(quadrant),PB_HALF_PI));
        if f64_gt(f64_magnitude(pb_wrap_pi(f64_sub(observed,expected))),ps_number(2,100)) {return 2;}
    }
    let angle=ps_ground_heading;let confidence=ps_ground_confidence;
    ps_x=f64_from_i64(99);ps_y=f64_from_i64(-99);ps_heading=PB_PI;ps_tcp=0;ps_gripper_frame=0;
    if ps_ground_heading_read()!=valid || ps_ground_heading!=angle || ps_ground_confidence!=confidence {return 3;}
    pb_zero(rgb,640*480*3);ps_cf_extract(rgb,0,ps_cf_points);if ps_ground_heading_read() {return 4;}return 0;
}
fn main() {
    if !pl_init() {return 1;}ps_cf_init();
'''+ '\n'.join(calls)+r'''
    pl_print(1,"Ground heading checks passed: empty/loaded RGB, biased heading prior, low-confidence rejection, blackout and poisoned truth\n");return 0;
}
'''
        entry, probe = directory/'heading.flex', directory/'heading'
        entry.write_text(source)
        compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler'))
        subprocess.run([compiler, str(entry), '-o', str(probe)], cwd=ROOT, check=True)
        subprocess.run([str(probe)], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
