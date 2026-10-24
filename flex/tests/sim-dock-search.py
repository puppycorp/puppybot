#!/usr/bin/env python3
"""Check circular-view coverage, truth isolation and recorded visual recovery."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def probe():
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main() {
    if !pl_init() { return 1; } ps_dock_search_anchor = alloc(32); let out = alloc(24);
    store64(ps_dock_search_anchor, ps_number(34, 100)); store64(ps_dock_search_anchor + 8, ps_number(-24, 100));
    store64(ps_dock_search_anchor + 16, ps_number(21, 10)); store64(ps_dock_search_anchor + 24, ps_number(4, 10));
    let text = alloc(16384); let b = alloc(32); pl_builder(b, text, 16384); pl_char(b, 91); let round = 0;
    while round < 2 {
        if round { pl_char(b, 44); ps_x = f64_from_i64(99); ps_y = f64_from_i64(-99); ps_heading = PB_PI; ps_case_bin = 0; ps_physics = 0; }
        pl_char(b, 91); let i = 0;
        while i < 36 {
            if i { pl_char(b, 44); } ps_dock_search_candidate(i, out); pl_char(b, 91); let k = 0;
            while k < 3 { if k { pl_char(b, 44); } pl_float(b, load64(out + k * 8)); k = k + 1; } pl_char(b, 93); i = i + 1;
        }
        pl_char(b, 93); round = round + 1;
    }
    pl_text(b, "]\n");
    ps_dock_hint = alloc(24); store64(ps_dock_hint, ps_number(34, 100)); store64(ps_dock_hint + 8, ps_number(-24, 100));
    ps_dock_hint_seen = ps_total; ps_dock_valid = 0; ps_dock_search_index = 7;
    if !ps_dock_search_attention() || ps_dock_search_view_start != 7 || ps_dock_search_index != 7 { return 2; }
    let saved = alloc(32); pb_copy(saved, ps_dock_search_anchor, 32);
    store64(ps_dock_hint, f64_from_i64(5)); ps_dock_search_index = 8;
    if ps_dock_search_attention() || ps_dock_search_view_start != 7 || ps_dock_search_index != 8 { return 3; }
    let k = 0; while k < 4 { if load64(saved + k * 8) != load64(ps_dock_search_anchor + k * 8) { return 4; } k = k + 1; }
    return pl_write(1, text, load64(b + 8));
}
'''
    with tempfile.TemporaryDirectory(prefix='dock-search-probe-', dir=ROOT/'build/flex/sim') as temporary:
        directory = Path(temporary)
        entry, binary = directory/'probe.flex', directory/'probe'
        entry.write_text(source)
        compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler'))
        subprocess.run([compiler, str(entry), '-o', str(binary)], cwd=ROOT, check=True)
        result = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True, check=True)
    first, poisoned = json.loads(result.stdout)
    assert first == poisoned, 'live world truth changed the camera-search goals'
    assert len(first) == 36 and all(all(math.isfinite(v) for v in pose) for pose in first)
    assert min(p[0] for p in first) < 0 and max(p[0] for p in first) > .7
    assert min(p[1] for p in first) < -.65 and max(p[1] for p in first) > .15
    for start in range(0, 36, 12):
        ring = first[start:start+12]
        radii = [math.hypot(x-.34, y+.24) for x, y, _ in ring]
        assert max(radii)-min(radii) < 1e-12 and .29 < radii[0] < .47
        headings = {round(h, 8) for _, _, h in ring}
        assert len(headings) == 12 and max(headings)-min(headings) > 5
    print('Circular search helpers passed: complete angular coverage, bounded radii, distinct viewpoints, poisoned-world isolation, fixed partial-cue anchor without resetting attempt budget')


def audit(path):
    segments = []
    current = None
    previous = None
    reacquired = None
    releases = 0
    for line in path.open():
        state = json.loads(line)
        case = state['case']
        search = case.get('boxSearch', {})
        active = search.get('active', False)
        if active:
            if current is None:
                current = dict(start=state['step'],poses=[],viewpoints=set())
                segments.append(current)
            assert 1 <= search['viewpoint'] <= search['maxViewpoints'] == 36
            pose = state['localization']['pose']
            current['poses'].append(pose)
            current['viewpoints'].add(search['viewpoint'])
        else:
            current = None
        dock = case['dockVision']
        if segments and dock['valid'] and dock['frameId'] >= segments[0]['start'] and dock['stableObservations'] >= 3:
            if reacquired is None:
                reacquired = state['step']
        if previous and previous['gripper']['held'] and not state['gripper']['held']:
            assert dock['valid'] and dock['frameId'] == dock['releaseFrameId'] == state['totalSteps']
            assert dock['stableObservations'] >= 3
            releases += 1
        assert state['physicsFault'] == state['vehicle']['queryFault'] == 0
        previous = state
    assert segments and reacquired is not None, 'circular motion did not produce a fresh stable box fix'
    poses = [pose for segment in segments for pose in segment['poses']]
    xspan = max(p[0] for p in poses)-min(p[0] for p in poses)
    yspan = max(p[1] for p in poses)-min(p[1] for p in poses)
    headings = {round(p[2], 2) for p in poses}
    assert xspan > .05 and yspan > .05 and len(headings) > 10, 'search stayed in the old straight lane'
    report = dict(schema='puppybot.box-search-audit.v1', reacquiredStep=reacquired,
                  xSpanM=xspan, ySpanM=yspan, distinctHeadings=len(headings),
                  freshCameraReleases=releases, placed=previous['case']['placed'],
                  missionPhase=previous['case']['phase'], missionReason=previous['case']['reason'])
    (path.parent/'search-audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path)
    args = parser.parse_args()
    probe()
    if args.trace:
        audit(args.trace)


if __name__ == '__main__':
    main()
