#!/usr/bin/env python3
"""Replay lost box vision with a raised payload, through a fresh RGB release."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import sys

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]

ROOT = Path(__file__).resolve().parents[2]


def replay(recorded, frame, output):
    output = output.resolve(); recorded = recorded.resolve()
    controller = output.with_name(output.name+'-controller')
    controller.mkdir(parents=True, exist_ok=False)
    original = ROOT/'flex/tests/sim-discovery-dock.py'
    text = original.read_text().replace('ROOT=Path(__file__).resolve().parents[2]', 'ROOT=Path('+repr(str(ROOT))+')')
    check = "assert current['case']['dockVision']['valid'] and current['case']['dockVision']['stableObservations']>=3"
    assert text.count(check) == 1
    text = text.replace(check, "assert not current['blocked'] and not current['collision']['armBlocked']")
    # Restore a previously learned RGB box pose without inventing freshness.
    # The ordinary camera survey must observe it again after recovery.
    restore = r'''
    dock=current['case']['dockVision'];restored='ps_identity(ps_dock_frame);ps_dock_seen=0;ps_dock_stable=0;ps_dock_valid=0;ps_dock_yaw='+word(dock['yawRad'])+';'
    for offset,value in [(0,math.cos(dock['yawRad'])),(8,math.sin(dock['yawRad'])),(32,-math.sin(dock['yawRad'])),(40,math.cos(dock['yawRad'])),(96,dock['positionM'][0]),(104,dock['positionM'][1])]:restored+=f'store64(ps_dock_frame+{offset},{word(value)});'
    source=source.replace('RESTORE_DOCK',restored)
'''
    entry = "    entry,binary=out/'probe.flex',out/'probe';entry.write_text(source)"
    assert text.count(entry) == 1
    text = text.replace(entry, restore+entry)
    start = ''' i=0;while i<3 {if !ps_tick(0) || !ps_dock_sample() {return 6;}i=i+1;}
 if ps_dock_stable<3 {ps_observation();pl_print(1,ps_json);return 7;}
 if !ps_dock_search_next() {return 8;}'''
    assert text.count(start) == 1
    text = text.replace(start, ''' RESTORE_DOCK
 ps_case_phase(7);if !ps_collect_stow_begin() {ps_observation();pl_print(1,ps_json);return 8;}''')
    final = ' ps_observation();pl_print(1,ps_json);syscall(3,ps_output,0,0,0,0,0);ps_render_close();return ps_case_placed!=PLACED+1;'
    assert text.count(final) == 1
    text = text.replace(final, ' let fd=ps_output;ps_output=-1;ps_observation();pl_print(1,ps_json);syscall(3,fd,0,0,0,0,0);ps_render_close();return ps_case_placed!=PLACED+1;')
    fixture = controller/'fixture.py'; fixture.write_text(text)
    files = [*ROOT.glob('flex/sim/*.flex'), ROOT/'flex/core/kinematics.flex',
             ROOT/'flex/vision/discovery.py', ROOT/'build/flex/sim/puppybot.bin',
             ROOT/'build/flex/sim/environments/apartment/apartment.bin',
             ROOT/'flex/sim/cases/discover-house-blocks-into-box.json',
             ROOT/'flex/tests/sim-discovery-pickup.py', original, Path(__file__).resolve(), fixture]
    expected = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    manifest = {}
    for path, digest in expected.items():
        saved = controller/'source-snapshot'/path.relative_to(ROOT)
        saved.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, saved)
        manifest[str(saved)] = digest
    spec = importlib.util.spec_from_file_location('restow_physics', fixture)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.replay(recorded, frame, output)
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in expected.items())
    previous = None; moving = 0
    for line in (output/'trace.jsonl').open():
        state = json.loads(line)
        if previous:
            assert state['step'] == previous['step']+1
            drive = previous['controller']['drive']; distance = (drive['leftSpeed']+drive['rightSpeed'])/20000
            heading = (previous['pose'][2]-distance/.18*math.tan(math.radians(drive['steeringAngleDeg']-90))+math.pi)%(2*math.pi)-math.pi
            expected_pose = [previous['pose'][0]+distance*math.cos(heading), previous['pose'][1]+distance*math.sin(heading), heading]
            assert math.dist(state['pose'][:2], expected_pose[:2]) < 1e-7
            assert abs((state['pose'][2]-heading+math.pi)%(2*math.pi)-math.pi) < 1e-7
            moving += bool(distance)
        previous = state
    for path in [output/'probe.flex', output/'probe']:
        manifest[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output/'source-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    report = json.loads((output/'dock-replay-audit.json').read_text())
    report.update(recordedCheckpoint=frame, actualMotionStepsChecked=moving,
                  priorDeliveriesRetained=state['case']['placed']-1,
                  settledInside=state['case']['inside'], sourceManifestMatches=True)
    (output/'restow-audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recorded', type=Path, required=True)
    parser.add_argument('--frame', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); replay(args.recorded, args.frame, args.output)


if __name__ == '__main__':
    main()
