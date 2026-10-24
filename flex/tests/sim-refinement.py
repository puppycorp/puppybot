#!/usr/bin/env python3
"""Exercise coarse-to-wrist association using a recorded orange-brick mismatch."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: f'import "{ROOT / "flex/sim" / m[1]}";', source, flags=re.MULTILINE)
    source += r'''
fn main() {
    pl_init(); ps_stock_pickup = 1; ps_case_target_colour = 6; ps_case_target = alloc(24); ps_brick_records = alloc(3 * 128); ps_brick_count = 3;
    // Recorded coarse estimate and the two visible wrist components from
    // route-trial8, step 11937; no body poses or identities are inputs.
    store64(ps_case_target, ps_number(6740384, 1000000)); store64(ps_case_target + 8, ps_number(-320856, 1000000));
    store64(ps_brick_records + 32, ps_number(6789566, 1000000)); store64(ps_brick_records + 40, ps_number(-351593, 1000000)); store64(ps_brick_records + 64, 1);
    store64(ps_brick_records + 160, ps_number(6795126, 1000000)); store64(ps_brick_records + 168, ps_number(-336653, 1000000)); store64(ps_brick_records + 192, 6);
    // A closer but incompatible colour must not win the wider association.
    pb_copy(ps_brick_records + 288, ps_case_target, 24); store64(ps_brick_records + 320, 2);
    ps_x = f64_from_i64(999); ps_y = f64_from_i64(-999); ps_physics = 1; ps_world_matrices = 1; ps_tcp = 1; ps_environment = 1;
    ps_case_refine_radius = ps_number(5, 100); if ps_case_refine_index() >= 0 { return 1; }
    ps_case_refine_radius = ps_number(10, 100); if ps_case_refine_index() != 1 { return 2; }
    ps_case_target_colour = 4; if ps_case_refine_index() >= 0 { return 3; }
    pl_print(1, "Wrist association passed: recorded far-ray mismatch, red/orange compatibility, nearer wrong-colour rejection, poisoned truth\n"); return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='refinement-probe-', dir=ROOT/'build/flex/sim') as temporary:
        entry = Path(temporary)/'probe.flex'
        binary = entry.with_suffix('')
        entry.write_text(source)
        env = dict(os.environ, FLEXSCRIPT_ROOT=os.environ.get('FLEXSCRIPT_ROOT', str(ROOT.parent/'flexscript')))
        subprocess.run([str(ROOT/'build/flex/pup-compiler'), str(entry), '-o', str(binary)], cwd=ROOT, env=env, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
