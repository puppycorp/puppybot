#!/usr/bin/env python3
"""Stage a small-rim-marker context check in a copied simulator only."""
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('rim_previous', ROOT / 'experiments/dock-rim-raster-audit-v1/transform.py')
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)


BLUE_SUPPORT = '''// A local colour cue for research only; it cannot identify a real box.
fn ps_dock_blue_support(x1, y1, x2, y2) {
    let cx = (x1 + x2) / 2; let cy = (y1 + y2) / 2; let count = 0;
    let y = pb_max(0, cy - 5); let end_y = pb_min(479, cy + 5);
    while y <= end_y { let x = pb_max(0, cx - 5); let end_x = pb_min(639, cx + 5);
        while x <= end_x {
            let p = ps_brick_rgb + (y * 640 + x) * 3;
            let r = load8(p); let g = load8(p + 1); let b = load8(p + 2);
            if b > 35 && b > g + 10 && g > r + 10 { count = count + 1; }
            x = x + 1;
        } y = y + 1;
    } return count;
}
'''


def transform(dock, main):
    dock, main = BASE.transform(dock, main)
    dock = BASE.once(dock, 'global ps_dock_count = 0;',
                     'global ps_dock_count = 0;\nglobal ps_dock_boundary_count = 0;')
    dock = BASE.once(dock, 'fn ps_dock_component(start) {', BLUE_SUPPORT + '\nfn ps_dock_component(start) {')
    anchor = '    let r = ps_dock_markers + ps_dock_count * 96; let u = f64_add(ps_number(sumx, tail), ps_number(1, 2));'
    dock = BASE.once(dock, anchor,
        '    let blue = 0; if ps_dock_small_components { blue = ps_dock_blue_support(x1, y1, x2, y2); if blue < 8 { return 0; } }\n' + anchor)
    dock = BASE.once(dock, 'ps_dock_count = ps_dock_count + 1; return 1;',
                     'ps_dock_count = ps_dock_count + 1; if ps_dock_small_components && blue < 100 { ps_dock_boundary_count = ps_dock_boundary_count + 1; } return 1;')
    dock = BASE.once(dock, '    ps_dock_count = 0; ps_dock_valid = 0; let i = 0;',
                     '    ps_dock_count = 0; ps_dock_boundary_count = 0; ps_dock_valid = 0; let i = 0;')
    dock = BASE.once(dock, '    pb_copy(ps_dock_calibration, ps_brick_pose, 96); if ps_dock_fit()',
                     '    pb_copy(ps_dock_calibration, ps_brick_pose, 96); if ps_dock_small_components && ps_dock_boundary_count < 2 { return 0; } if ps_dock_fit()')
    return dock, main
