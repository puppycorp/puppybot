#!/usr/bin/env python3
"""Check post-delivery exploration resumption over observed floor."""
import argparse
import hashlib
import importlib.util
import math
import os
from pathlib import Path
import re
import json
import subprocess
import tempfile
import shutil
import sys

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]

ROOT = Path(__file__).resolve().parents[2]


def control():
    source = (ROOT/'flex/sim/main.flex').read_text().replace('fn main(argc, argv)', 'fn ps_application_main(argc, argv)')
    source = re.sub(r'^import "([^"]+)";', lambda m: 'import '+json.dumps(str(ROOT/'flex/sim'/m[1]))+';', source, flags=re.MULTILINE)
    source += r'''
fn main() {
    if !pl_init() || !ps_catalog_load() || !ps_case_load(ps_case_find("discover-house-blocks-into-box")) || !ps_model_load("build/flex/sim/puppybot.bin") { return 1; }
    ps_robot=alloc(8192);ps_system=alloc(2048);ps_config=alloc(448);ps_app=alloc(2048);ps_bus=alloc(16384);ps_plant=alloc(2048);ps_trace=alloc(69632);ps_json=alloc(16384);ps_builder=alloc(32);pb_config_default(ps_config);
    if !ps_reset() { return 2; } ps_house_ready=1;ps_collect_busy=0;
    ps_identity(ps_dock_frame);store64(ps_dock_frame+96,ps_number(-2,1));store64(ps_dock_frame+104,ps_number(-2,1));ps_dock_yaw=0;
    if ps_collect_resume_plan() { return 3; }
    let i=0;while i<40000 {store8(ps_nav_map+i,0);store8(ps_discovery_observed+i,0);i=i+1;}
    i=0;while i<1000000 {store8(ps_discovery_detail+i,0);i=i+1;}ps_discovery_detail_ready=1;
    // Explicit synthetic floor is confined to this control test. Poisoned
    // world inputs cannot supply the saved goal or authorize a route.
    ps_environment=1;ps_environment_start=1;ps_environment_count=99999;
    ps_x=f64_nan();ps_y=f64_from_i64(99);ps_heading=PB_PI;
    store64(ps_collect_resume_goal,PB_ONE);store64(ps_collect_resume_goal+8,0);store64(ps_collect_resume_goal+16,0);
    ps_collect_resume_valid=1;ps_collect_resume_placed=0;ps_case_placed=0;
    if ps_collect_resume_plan() || !ps_collect_resume_valid || ps_collect_resume_tries { return 4; }
    ps_case_placed=1;
    if !ps_collect_resume_plan() || ps_collect_resume_valid || ps_collect_resume_count!=1 || !ps_nav_path_count || load64(ps_nav_goal)!=PB_ONE { return 5; }
    let drive=pb_robot_drive(ps_robot);if load64(drive+48) || load64(drive+56) { return 6; }
    // A nearby scan location does not warrant another departure.
    ps_collect_resume_valid=1;ps_collect_resume_tries=0;store64(ps_collect_resume_goal,ps_number(1,10));
    if ps_collect_resume_plan() || ps_collect_resume_valid || ps_collect_resume_count!=1 { return 7; }
    // A confirmed, uncollected RGB target retains its existing priority.
    store64(ps_collect_resume_goal,PB_ONE);ps_collect_resume_valid=1;ps_collect_count=1;
    pb_zero(ps_collect_points,64);store64(ps_collect_points,ps_number(15,10));store64(ps_collect_points+32,3);
    if ps_collect_resume_plan() || ps_collect_resume_valid || ps_collect_resume_tries { return 8; }ps_collect_count=0;
    // A destination associated with a protective stop is not revisited.
    ps_collect_resume_valid=1;ps_discovery_failed_count=1;store64(ps_discovery_failed_goals,PB_ONE);store64(ps_discovery_failed_goals+8,0);
    if ps_collect_resume_plan() || ps_collect_resume_valid { return 9; }ps_discovery_failed_count=0;
    // Unknown floor rejects all retries; no cells or motor commands change.
    i=0;while i<40000 {store8(ps_nav_map+i,1);store8(ps_discovery_observed+i,1);i=i+1;}
    i=0;while i<1000000 {store8(ps_discovery_detail+i,1);i=i+1;}
    ps_collect_resume_valid=1;ps_collect_resume_tries=0;let retry=0;
    while retry<3 {
        if ps_collect_resume_plan() || ps_collect_resume_tries!=retry+1 || ps_collect_resume_valid!=(retry<2) { return 10; }retry=retry+1;
    }
    i=0;while i<40000 {if load8(ps_nav_map+i)!=1 || load8(ps_discovery_observed+i)!=1 {return 11;}i=i+1;}
    i=0;while i<1000000 {if load8(ps_discovery_detail+i)!=1 {return 12;}i=i+1;}
    if load64(drive+48) || load64(drive+56) || ps_collect_resume_count!=1 { return 13; }
    pl_print(1,"Exploration resumption passed: delivery gate, observed-floor planning, RGB priority, failed-goal exclusion, bounded unknown-floor retries and poisoned world inputs\n");return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='discovery-resume-control-', dir=ROOT/'build/flex/sim') as temporary:
        directory = Path(temporary)
        entry, binary = directory/'probe.flex', directory/'probe'
        entry.write_text(source)
        subprocess.run([os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler')), str(entry), '-o', str(binary)], cwd=ROOT, check=True)
        subprocess.run([str(binary)], cwd=ROOT, check=True)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def audit(path, checkpoint, goal, baseline):
    import cv2
    import numpy as np
    pickup = module('resume_geometry', ROOT/'flex/tests/sim-discovery-pickup.py')
    geometry = module('resume_case', ROOT/'flex/tests/sim-cases.py')
    definition = json.loads((ROOT/'flex/sim/cases/discover-house-blocks-into-box.json').read_text())
    judge = pickup.HeldGeometry(); previous = None; camera = 0; distance = 0.; nearest = math.inf; captures = []; releases = []; refinement = None
    frames = {}; requests = []
    for file in (path.parent/'map/episode-0').glob('input-*.json'):
        request = json.loads(file.read_text())
        if all(Path(f['rgb']).resolve().parent == (path.parent/'map/episode-0').resolve() for f in request['frames']):
            requests.append(request)
            for frame in request['frames']: frames[frame['frameId']] = frame
    checked = set(); poses = {}
    for line in path.open():
        state = json.loads(line); case = state['case']; discovery = state['discovery']
        poses[state['step']] = state['localization']['pose']
        assert not state['physicsFault'] and not state['vehicle']['queryFault']
        assert not discovery['suppliedMap'] and not discovery['worldPoseInput'] and case['navigation']['coverageCount'] == 0
        judge.check(state)
        nearest = min(nearest, math.dist(state['localization']['pose'][:2], goal[:2]))
        if previous:
            drive = previous['controller']['drive']; ds = (drive['leftSpeed']+drive['rightSpeed'])/20000
            heading = (previous['pose'][2]-ds/.18*math.tan(math.radians(drive['steeringAngleDeg']-90))+math.pi)%(2*math.pi)-math.pi
            expected = [previous['pose'][0]+ds*math.cos(heading), previous['pose'][1]+ds*math.sin(heading), heading]
            if state['blocked']: expected = previous['pose']
            assert math.dist(state['pose'][:2], expected[:2]) < 1e-7
            assert abs((state['pose'][2]-expected[2]+math.pi)%(2*math.pi)-math.pi) < 1e-7
            distance += math.dist(state['pose'][:2], previous['pose'][:2])
            if case['visualRefinements'] > previous['case']['visualRefinements']: refinement = (state['step'], state['pose'])
            if state['collision']['armBlocked']:
                assert not state['gripper']['held'] and state['ticks'] == previous['ticks'] and math.dist(state['pose'], previous['pose']) < 1e-9
            if state['gripper']['grasps'] > previous['gripper']['grasps']:
                assert state['gripper']['captureContactMask'] == 3 and refinement and state['step']-refinement[0] <= 1500 and math.dist(state['pose'], refinement[1]) < 1e-7
                captures.append(state['gripper']['body'])
            if state['gripper']['releases'] > previous['gripper']['releases']:
                dock = case['dockVision']; assert dock['valid'] and dock['frameId'] == dock['releaseFrameId'] == state['step'] and dock['stableObservations'] >= 3
                releases.append(state['step'])
        if case['perception']['frameId'] == state['step']:
            metadata = json.loads((path.parent/'sensor'/f'frame-{state["step"]}.png.camera.json').read_text())
            eye, axis = pickup.camera_frame_error(state, case['perception']['calibration'], metadata)
            assert eye < .003 and axis < .00003; camera += 1
        if state['step'] in frames:
            frame = frames[state['step']]; assert frame['calibration'] == case['perception']['calibration']
            assert set(frame) == {'rgb','frameId','calibration','robot'}
            assert np.allclose(frame['robot'], judge.robot_boxes(state), atol=1e-8, rtol=0)
            rgb = cv2.cvtColor(cv2.imread(str(path.parent/'sensor'/f'frame-{state["step"]}.png')), cv2.COLOR_BGR2RGB)
            assert Path(frame['rgb']).read_bytes() == rgb.tobytes(); checked.add(state['step'])
        previous = state
    assert requests and checked == set(frames)
    # The old state is used only to restore the physical fixture. The robot
    # receives fresh images and its own map and estimate throughout this test.
    for request in requests:
        assert set(request) == {'schema','frameId','newScan','pose','frames'}
        assert request['pose'] == poses[request['frameId']]
    prior = {o['id'] for o in checkpoint['case']['objects'] if o['inside']}
    for obj in state['case']['objects']:
        if obj['id'] in prior: assert obj['inside']; geometry.contained(obj, definition, state['case']['container'])
    manifest = json.loads((path.parent/'source-manifest.json').read_text())
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest for name, digest in manifest.items())
    resumed = state['discovery']['pickup'].get('resumedRoutes', 0)
    result = dict(passed=True, checkpointReplayOnly=True, fullMissionVerified=False, baseline=baseline, steps=state['step'], ordinaryDistanceM=distance, closestOwnDistanceToDepartureM=nearest, ownDepartureReached=nearest<.3, resumedRoutes=resumed, freshStereoPairs=len(requests), cameraFramesChecked=camera, heldFramesChecked=judge.frames, capturedBodies=captures, releases=releases, priorDeliveriesContained=len(prior), additionalDriveStops=state['discovery']['protectiveStops']-checkpoint['discovery']['protectiveStops'], additionalArmStops=state['discovery']['armProtectiveStops']-checkpoint['discovery']['armProtectiveStops'], sourceManifestMatches=True)
    (path.parent/'resume-audit.json').write_text(json.dumps(result, indent=2)+'\n'); print(json.dumps(result, indent=2))
    return result


def replay(recorded, context, output, baseline=False):
    context = context.resolve(); output = output.resolve(); recorded = recorded.resolve()
    saved = json.loads(context.read_text()); state = saved['checkpoint']; departure = saved['departure']['state']
    assert not state['gripper']['held'] and not state['discovery']['pickup']['busy']
    goal = [*departure['localization']['pose'][:2], departure['discovery']['scanBearingRad']]
    controller = output.with_name(output.name+'-controller'); controller.mkdir(parents=True, exist_ok=False)
    for file in (ROOT/'flex/sim').glob('*.flex'):
        original = file
        if baseline and file.name in ('collect.flex', 'discovery.flex'): original = recorded.parent/'source-snapshot/flex/sim'/file.name
        source = original.read_text()
        def replace_import(match):
            target = (file.parent/match[1]).resolve()
            if target.parent == (ROOT/'flex/sim').resolve(): target = controller/target.name
            return 'import '+json.dumps(str(target))+';'
        source = re.sub(r'^import "([^"]+)";', replace_import, source, flags=re.M)
        source = source.replace('flex/vision/discovery.py', str(controller/'worker.py'))
        (controller/file.name).write_text(source)
    shutil.copyfile(ROOT/'flex/vision/discovery.py', controller/'worker.py')
    builder = module('resume_replay', ROOT/'flex/tests/sim-discovery-retrace.py')
    backoff = module('resume_odometry', ROOT/'flex/tests/sim-discovery-backoff.py')
    approach = module('resume_words', ROOT/'flex/tests/sim-discovery-approach.py'); word = approach.word
    bad, random_state, draws = backoff.recorded_context(recorded, state['step'], state)
    events = json.loads((recorded.parent/'drive-stop-review.json').read_text())['events']
    events = [e for e in events if e['step'] <= state['step']]
    contacts = []
    for event in events:
        drive = event['command']; contacts.append([*event['ownPose'], 1 if drive['leftSpeed'] > 0 else -1, -math.tan(math.radians(drive['steeringAngleDeg']-90))/.18])
    builder.checkpoint = lambda *args: (state, [], contacts, None)
    native = builder.NATIVE[:builder.NATIVE.index(' if !ps_discovery_next_sector()')]
    native = native.replace('ps_discovery_scans=SCANS-1;', 'ps_discovery_scans=SCANS;')
    native = native.replace('ps_crumb_enabled=0;', 'ps_crumb_enabled=1;ps_crumb_recording=1;')
    for i, obj in enumerate(state['case']['objects']):
        if obj['inside']: native += f'store64(ps_case_objects+{i*256+192},1);'
    native += f'ps_local_random={random_state};ps_local_distance={word(state["localization"]["estimatedDistanceM"])};'
    native += f'ps_discovery_failed_count={len(events)};ps_discovery_failed_next={len(events)};'
    for i,event in enumerate(events):
        for k,value in enumerate(event['selectedGoal'][:2]): native += f'store64(ps_discovery_failed_goals+{i*16+k*8},{word(value)});'
    native += f'ps_discovery_bad_count={len(bad)};ps_discovery_bad_next={len(bad)};'
    for i,point in enumerate(bad):
        for k,value in enumerate(point): native += f'store64(ps_discovery_bad_poses+{i*16+k*8},{word(value)});'
    for i,value in enumerate(state['localization']['pose']): native += f'store64(ps_house_home+{i*8},{word(value)});'
    focus = saved['departure']['previous']['case']['navigation']['goal']
    for i,value in enumerate(focus): native += f'store64(ps_nav_goal+{i*8},{word(value)});'
    native += 'ps_discovery_frontier_focus(ps_nav_goal);'
    if not baseline:
        native += f'ps_collect_resume_valid=1;ps_collect_resume_placed={state["case"]["placed"]-1};'
        for i,value in enumerate(goal): native += f'store64(ps_collect_resume_goal+{i*8},{word(value)});'
    native += 'if !ps_collect_search_begin() {return 5;}let n=0;while n<20000 && ps_discovery_phase!=7 {if !ps_tick(0) {return 6;}n=n+1;}ps_output=-1;ps_observation();pl_print(1,ps_json);ps_render_close();return 0;}\n'
    builder.NATIVE = native
    builder.audit = lambda path, checkpoint, history: audit(path, checkpoint, goal, baseline)
    builder.replay(recorded, state['step'], output, initial_map=context.parent/'map', controller=controller)
    (output/'resume-setup.json').write_text(json.dumps(dict(checkpoint=state['step'], departure=departure['step'], ownGoal=goal, odometryDraws=draws, baseline=baseline, fullMissionVerified=False), indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recorded', type=Path); parser.add_argument('--context', type=Path); parser.add_argument('--output', type=Path); parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    if args.recorded:
        assert args.context and args.output
        replay(args.recorded, args.context, args.output, args.baseline)
    else: control()


if __name__ == '__main__':
    main()
