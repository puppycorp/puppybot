#!/usr/bin/env python3
"""Compare a discovery map with simulator geometry, strictly offline."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import time

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def latest_state(trace):
    with trace.open('rb') as source:
        source.seek(max(0, trace.stat().st_size-100000))
        lines = source.read().splitlines()
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            pass
    raise ValueError('trace has no complete observation')


def checkpoint(run):
    """Read between workers, checking both trace state and immutable masks."""
    directory = run/'map/episode-0'
    deadline = time.monotonic()+15
    while time.monotonic() < deadline:
        before = latest_state(run/'trace.jsonl')['discovery']
        if before['phase'] == 3 or Path(before['output']).resolve() != directory.resolve():
            time.sleep(.05)
            continue
        metadata = json.loads((directory/'map.json').read_text())
        frame = metadata['frameId']
        if frame != before['mapFrameId']:
            time.sleep(.05)
            continue
        raw = (directory/'evidence.npz').read_bytes()
        after = latest_state(run/'trace.jsonl')['discovery']
        if after['phase'] == 3 or after['mapFrameId'] != frame or after['output'] != before['output']:
            continue
        with np.load(io.BytesIO(raw)) as data:
            arrays = {name: data[name].copy() for name in data.files}
        cells = metadata['cells']
        free = (arrays['free'] >= 3) & (arrays['occupied'] < 2)
        occupied = arrays['occupied'] >= 2
        fine = ((arrays['floorDetail'] >= 3) &
                ~((arrays['heightConfirmed'] != 0) & (arrays['detail'] >= 2)))
        observed = (directory/f'observed-{frame}.bin').read_bytes()
        detail = (directory/f'observed-detail-{frame}.bin').read_bytes()
        if free.shape != (cells, cells) or (~free).astype(np.uint8).tobytes() != observed:
            continue
        if (~fine).astype(np.uint8).tobytes() != detail:
            continue
        assert int(free.sum()) == metadata['freeCells']
        assert int(occupied.sum()) == metadata['occupiedCells']
        return metadata, arrays, raw, free, occupied, fine
    raise ValueError('could not obtain a coherent map checkpoint between mapping workers')


def read_environment(path):
    raw = path.read_bytes()
    magic, count, vertices, overview = struct.unpack_from('<8s3Q', raw)
    assert magic == b'PBENV001' and 1 <= count <= 160 and vertices == overview
    assert len(raw) == 256+count*128+vertices*72
    bounds = struct.unpack_from('<4d', raw, 64)
    boxes = []
    for index in range(count):
        offset = 256+index*128
        name = raw[offset:offset+48].split(b'\0')[0].decode('ascii')
        values = struct.unpack_from('<7d', raw, offset+48)
        boxes.append(dict(name=name, centre=values[:3], half=values[3:6], yaw=values[6]))
    return bounds, boxes


def world_points(cells, resolution, origin, initial_pose):
    axis = (np.arange(cells)+.5)*resolution
    x, y = np.meshgrid(axis+origin[0], axis+origin[1])
    c, s = math.cos(initial_pose[2]), math.sin(initial_pose[2])
    return initial_pose[0]+c*x-s*y, initial_pose[1]+s*x+c*y


def box_mask(x, y, centre, half, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    dx, dy = x-centre[0], y-centre[1]
    return (np.abs(c*dx+s*dy) <= half[0]) & (np.abs(-s*dx+c*dy) <= half[1])


def ground_truth(x, y, bounds, boxes, height_band=(.02, .45)):
    inside = (x >= bounds[0]) & (x < bounds[2]) & (y >= bounds[1]) & (y < bounds[3])
    occupied = np.zeros(x.shape, bool)
    for box in boxes:
        centre, half = box['centre'], box['half']
        if centre[2]+half[2] > height_band[0] and centre[2]-half[2] < height_band[1]:
            occupied |= box_mask(x, y, centre, half, box['yaw'])
    return inside & ~occupied, occupied, inside


def task_footprints(x, y, initial, current, definition):
    """Exclude movable task footprints from structural floorplan scoring."""
    ignored = np.zeros(x.shape, bool)
    sizes = {item['id']: item['halfSize'] for item in definition['objects']}
    for state in (initial, current):
        for item in state['case']['objects']:
            if state['gripper']['held'] and item['body'] == state['gripper']['body']:
                continue
            qx, qy, qz, qw = item['quaternion']
            yaw = math.atan2(2*(qw*qz+qx*qy), 1-2*(qy*qy+qz*qz))
            ignored |= box_mask(x, y, item['position'], sizes[item['id']], yaw)
        container = state['case']['container']
        qx, qy, qz, qw = container['quaternion']
        yaw = math.atan2(2*(qw*qz+qx*qy), 1-2*(qy*qy+qz*qz))
        spec = definition['container']
        half = [size/2+spec['wallThickness'] for size in spec['innerSize'][:2]]
        ignored |= box_mask(x, y, container['position'], half, yaw)
    return ignored


def ratio(numerator, denominator):
    return float(numerator/denominator) if denominator else None


def score(predicted_free, predicted_occupied, true_free, true_occupied, resolution, ignored=None):
    eligible = np.ones(true_free.shape, bool) if ignored is None else ~ignored
    pf, po = predicted_free & eligible, predicted_occupied & eligible
    tf, to = true_free & eligible, true_occupied & eligible
    assert not np.any(pf & po) and not np.any(tf & to)
    free_tp = int((pf & tf).sum())
    free_fp = int((pf & ~tf).sum())
    occupied_tp = int((po & to).sum())
    occupied_fp = int((po & ~to).sum())
    area = resolution**2
    return dict(
        freeFloorCoverage=ratio(free_tp, int(tf.sum())),
        freeSpacePrecision=ratio(free_tp, int(pf.sum())),
        freeSpaceIoU=ratio(free_tp, int((pf | tf).sum())),
        obstaclePrecision=ratio(occupied_tp, int(po.sum())),
        obstacleRecall=ratio(occupied_tp, int(to.sum())),
        obstacleIoU=ratio(occupied_tp, int((po | to).sum())),
        knownLabelAgreement=ratio(free_tp+occupied_tp, int((pf | po).sum())),
        referenceFreeFloorM2=float(tf.sum()*area),
        correctlyMappedFreeFloorM2=free_tp*area,
        falselyFreeM2=free_fp*area,
        falselyOccupiedM2=occupied_fp*area,
        predictedFreeM2=float(pf.sum()*area),
        referenceObstacleM2=float(to.sum()*area),
    )


def trace_states(trace, frame):
    first = current = None
    poses = []
    with trace.open('rb') as source:
        for line in source:
            if not line.endswith(b'\n'):
                break
            marker = b'"totalSteps":'
            start = line.find(marker)+len(marker)
            step = int(line[start:line.find(b',', start)])
            if step > frame:
                break
            if first is not None and step != frame and step % 50:
                continue
            state = json.loads(line)
            if first is None:
                first = state
            poses.append((step, state['pose'], state['localization']['pose']))
            if step == frame:
                current = state
                break
    assert first is not None and current is not None, 'checkpoint frame absent from trace'
    assert first['localization']['initialPrior'] == 'local-origin'
    assert not current['discovery']['suppliedMap'] and not current['discovery']['worldPoseInput']
    assert current['case']['navigation']['coverageCount'] == 0
    return first, current, poses


def pose_metrics(poses, initial_pose):
    c, s = math.cos(initial_pose[2]), math.sin(initial_pose[2])
    rows = []
    for step, actual, estimated in poses:
        dx, dy = actual[0]-initial_pose[0], actual[1]-initial_pose[1]
        x, y = c*dx+s*dy, -s*dx+c*dy
        heading = (estimated[2]-actual[2]+initial_pose[2]+math.pi)%(2*math.pi)-math.pi
        rows.append((step, math.dist((x, y), estimated[:2]), abs(heading)))
    values = np.asarray(rows)
    return dict(samples=len(rows), samplingIntervalSteps=50,
                positionRMSEM=float(np.sqrt(np.mean(values[:, 1]**2))),
                positionP95M=float(np.quantile(values[:, 1], .95)),
                maximumSampledPositionErrorM=float(values[:, 1].max()),
                endpointPositionErrorM=float(values[-1, 1]),
                headingRMSEDeg=float(np.degrees(np.sqrt(np.mean(values[:, 2]**2)))))


def history(directory, frame, true_free, ignored, cells):
    scale = true_free.shape[0]//cells
    weights = (true_free & ~ignored).reshape(cells, scale, cells, scale).sum(axis=(1, 3))
    eligible = (~ignored).reshape(cells, scale, cells, scale).sum(axis=(1, 3))
    result = []
    for path in directory.glob('observation-*.json'):
        try:
            metadata = json.loads(path.read_text())
        except ValueError:
            continue
        step = metadata['frameId']
        if step > frame:
            continue
        free = np.frombuffer((directory/f'observed-{step}.bin').read_bytes(), np.uint8).reshape(cells, cells) == 0
        tp = int(weights[free].sum())
        total = int(eligible[free].sum())
        result.append(dict(step=step, freeFloorCoverage=ratio(tp, int(weights.sum())),
                           freeSpacePrecision=ratio(tp, total)))
    return sorted(result, key=lambda item: item['step'])


def figure(output, metadata, true_free, true_occupied, predicted_free, predicted_occupied, ignored, metrics, timeline):
    os.environ.setdefault('MPLCONFIGDIR', '/tmp/puppybot-map-matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    shape = true_free.shape
    reference = np.full((*shape, 3), [.16, .18, .21])
    reference[true_free] = [.94, .94, .91]
    reference[true_occupied] = [.04, .05, .07]
    learned = np.full((*shape, 3), [.24, .26, .29])
    learned[predicted_free] = [.87, .94, .88]
    learned[predicted_occupied] = [.85, .25, .22]
    agreement = reference.copy()
    agreement[true_free] = [.78, .80, .82]
    agreement[predicted_free & true_free] = [.20, .70, .40]
    agreement[predicted_free & ~true_free] = [.94, .18, .18]
    agreement[predicted_occupied & ~true_occupied] = [.98, .63, .15]
    agreement[ignored] = [.54, .44, .65]
    rows, cols = np.nonzero(true_free | true_occupied | predicted_free | predicted_occupied)
    r0, r1 = max(0, int(rows.min())-10), min(shape[0], int(rows.max())+11)
    c0, c1 = max(0, int(cols.min())-10), min(shape[1], int(cols.max())+11)
    resolution = metadata['resolutionM']/5
    ox, oy = metadata['originM']
    extent = (ox+c0*resolution, ox+c1*resolution, oy+r0*resolution, oy+r1*resolution)
    fig, axes = plt.subplots(1, 3, figsize=(16, 6.5), constrained_layout=True)
    titles = ['Reference floorplan (offline judge)', 'Learned map (same fixed frame)', 'Agreement with reference']
    for axis, data, title in zip(axes, (reference, learned, agreement), titles):
        axis.imshow(data[r0:r1, c0:c1], origin='lower', extent=extent, interpolation='nearest')
        axis.set(title=title, xlabel='Local x (m)', ylabel='Local y (m)', aspect='equal')
    axes[2].legend(handles=[Patch(color=color, label=label) for color, label in (
        ([.20, .70, .40], 'Correct free floor'), ([.94, .18, .18], 'Falsely free'),
        ([.98, .63, .15], 'Falsely occupied'), ([.78, .80, .82], 'Unmapped free floor'),
        ([.54, .44, .65], 'Task footprint excluded'))], loc='upper left', fontsize=8)
    fig.suptitle(f"Frame {metadata['frameId']:,} | Floor coverage {metrics['freeFloorCoverage']:.1%} | Free-space precision {metrics['freeSpacePrecision']:.1%}\nStructural floorplan, height band 2-45 cm; fixed initial frame, no best-fit alignment", fontsize=13)
    fig.savefig(output/'comparison.png', dpi=160)
    plt.close(fig)
    fig, axis = plt.subplots(figsize=(10, 4), constrained_layout=True)
    for name, label in (('freeFloorCoverage', 'Free floor coverage'), ('freeSpacePrecision', 'Free-space precision')):
        axis.plot([row['step']*.02/60 for row in timeline],
                  [100*row[name] if row[name] is not None else float('nan') for row in timeline], label=label)
    axis.set(xlabel='Simulation time (minutes)', ylabel='Percent', ylim=(0, 101), title='Exploration quality over time')
    axis.grid(alpha=.25)
    axis.legend()
    fig.savefig(output/'progress.png', dpi=160)
    plt.close(fig)


def benchmark(run, output, environment=None, case_definition=None):
    metadata, arrays, raw, free, occupied, fine = checkpoint(run)
    manifest = json.loads((run/'source-manifest.json').read_text())
    assert all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest for name, digest in manifest.items())
    candidates = []
    for name in manifest:
        path = ROOT/name
        if path.suffix == '.bin':
            with path.open('rb') as source:
                if source.read(8) == b'PBENV001':
                    candidates.append(path)
    assert len(candidates) == 1, 'the run manifest must identify one actual environment asset'
    if environment is None:
        environment = candidates[0]
    assert hashlib.sha256(environment.read_bytes()).hexdigest() == hashlib.sha256(candidates[0].read_bytes()).hexdigest(), 'reference environment differs from the recorded runtime asset'
    bounds, boxes = read_environment(environment)
    initial, current, poses = trace_states(run/'trace.jsonl', metadata['frameId'])
    assert tuple(current['environment']['bounds']) == bounds
    assert current['environment']['staticColliders'] == len(boxes)
    if case_definition is None:
        case_definition = run/'case-definition.json'
        if not case_definition.exists():
            case_definition = ROOT/'flex/sim/cases'/f"{initial['case']['id']}.json"
    definition = json.loads(case_definition.read_text())
    assert hashlib.sha256(case_definition.read_bytes()).hexdigest() in manifest.values(), 'case definition is not a recorded runtime input'
    assert definition['id'] == initial['case']['id']
    assert {item['id'] for item in definition['objects']} == {item['id'] for item in initial['case']['objects']}
    cells, resolution = metadata['cells']*5, metadata['resolutionM']/5
    x, y = world_points(cells, resolution, metadata['originM'], initial['pose'])
    true_free, true_occupied, inside = ground_truth(x, y, bounds, boxes)
    ignored = task_footprints(x, y, initial, current, definition)
    predicted_free = np.repeat(np.repeat(free, 5, axis=0), 5, axis=1)
    predicted_occupied = np.repeat(np.repeat(occupied, 5, axis=0), 5, axis=1)
    metrics = score(predicted_free, predicted_occupied, true_free, true_occupied, resolution, ignored)
    detail_metrics = score(fine, np.zeros_like(fine), true_free, true_occupied, resolution, ignored)
    detail_metrics = {key: value for key, value in detail_metrics.items() if key.startswith('free') or key in ('referenceFreeFloorM2', 'correctlyMappedFreeFloorM2', 'falselyFreeM2', 'predictedFreeM2')}
    timeline = history(run/'map/episode-0', metadata['frameId'], true_free, ignored, metadata['cells'])
    output.mkdir(parents=True, exist_ok=False)
    (output/'checkpoint-evidence.npz').write_bytes(raw)
    (output/'checkpoint-map.json').write_text(json.dumps(metadata, indent=2)+'\n')
    result = dict(schema='puppybot.map-benchmark.v1', evaluationOnly=True,
                  referenceSuppliedToRobot=False, sourceManifestVerified=True,
                  sourceRun=str(run.resolve()), mappedFrame=metadata['frameId'],
                  referenceEnvironment=str(environment.resolve()),
                  referenceEnvironmentSHA256=hashlib.sha256(environment.read_bytes()).hexdigest(),
                  referenceCaseDefinition=str(case_definition.resolve()),
                  referenceCaseDefinitionSHA256=hashlib.sha256(case_definition.read_bytes()).hexdigest(),
                  alignment='fixed initial local frame; no best-fit registration',
                  initialActualPose=initial['pose'], assessmentResolutionM=resolution,
                  obstacleHeightBandM=[.02, .45],
                  scope='Structural floorplan: static walls/furniture. Initial/current task-object and box footprints excluded; all other unknown free floor reduces coverage.',
                  excludedTaskFootprintM2=float((ignored & inside).sum()*resolution**2),
                  coarseMap=metrics, fineFloorEvidence=detail_metrics,
                  odometry=pose_metrics(poses, initial['pose']),
                  mission=dict(placed=current['case']['placed'], required=current['case']['required'], passed=current['case']['passed']),
                  history=timeline, fullMissionVerified=False)
    (output/'benchmark.json').write_text(json.dumps(result, indent=2)+'\n')
    figure(output, metadata, true_free, true_occupied, predicted_free, predicted_occupied, ignored, metrics, timeline)
    print(json.dumps(dict(output=str(output.resolve()), mappedFrame=metadata['frameId'], **metrics, odometry=result['odometry'])), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--environment', type=Path)
    parser.add_argument('--case-definition', type=Path)
    args = parser.parse_args()
    benchmark(args.run.resolve(), args.output.resolve(), args.environment, args.case_definition)


if __name__ == '__main__':
    main()
