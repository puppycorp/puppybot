#!/usr/bin/env python3
"""Build frontier training examples by replaying actual saved wrist RGB pairs.

Actor features use only replayed partial maps and estimated poses. Reference
geometry and actual poses enter the offline labels after feature extraction.
The labels approximate future visibility; they are not counterfactual RGB runs.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

import cv2
import numpy as np

from bootstrap import ENDS, PATHS
from policy import FEATURE_NAMES, features, sha256


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def rotation(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s], [s, c]])


class VisibilityTeacher:
    def __init__(self, environment, initial, evaluator):
        bounds, boxes = evaluator.read_environment(environment)
        x, y = evaluator.world_points(200, .1, [-10, -10], initial)
        self.free = evaluator.ground_truth(x, y, bounds, boxes)[0]
        self.unsafe = cv2.dilate((~self.free).astype(np.uint8),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))).astype(bool)
        self.initial = np.asarray(initial)
        self.cache = {}

    def visible(self, row, col):
        key = int(row), int(col)
        if key not in self.cache:
            rows = np.clip(PATHS[:, :, 0]+row, 0, 199)
            cols = np.clip(PATHS[:, :, 1]+col, 0, 199)
            clear = self.free[rows, cols].all(axis=1)
            rr = np.clip(ENDS[clear, 0]+row, 0, 199)
            cc = np.clip(ENDS[clear, 1]+col, 0, 199)
            self.cache[key] = np.unique(rr*200+cc)
        return self.cache[key]

    def local_truth(self, xy, own_pose, actual_pose):
        world = (np.asarray(xy)-own_pose[:2]) @ rotation(actual_pose[2]-own_pose[2]).T+actual_pose[:2]
        return (world-self.initial[:2]) @ rotation(-self.initial[2]).T

    def labels(self, known, own_pose, actual_pose, candidates, distances):
        rows, cols = np.nonzero(known)
        xy = np.column_stack((cols, rows))*.1-9.95
        projected = self.local_truth(xy, own_pose, actual_pose)
        cells = np.floor((projected+10)/.1).astype(int)
        valid = ((cells >= 0) & (cells < 200)).all(axis=1)
        observed = np.zeros(40000, bool)
        observed[cells[valid, 1]*200+cells[valid, 0]] = True
        xy = np.asarray([candidate[1][:2] for candidate in candidates])
        cells = np.floor((self.local_truth(xy, own_pose, actual_pose)+10)/.1).astype(int)
        own_cells = np.floor((xy+10)/.1).astype(int)
        target = []
        for (col, row), (own_col, own_row) in zip(cells, own_cells):
            risk = not (0 <= row < 200 and 0 <= col < 200) or self.unsafe[np.clip(row, 0, 199), np.clip(col, 0, 199)]
            ids = self.visible(row, col) if not risk else []
            gain = float((~observed[ids]).sum())*.01 if len(ids) else 0.
            utility = gain/(1+distances[(int(own_row), int(own_col))])
            target.append([utility, float(risk)])
        target = np.asarray(target, np.float32)
        raw = target[:, 0].copy()
        if raw.max() > 0:
            target[:, 0] /= raw.max()
        return target, raw


def replay(entry, mapper_path, evaluator, group_start, maximum_candidates):
    run = Path(entry['run'])
    requests = [json.loads(p.read_text()) for p in sorted(
        (run/'map/episode-0').glob('input-*.json'), key=lambda p: int(p.stem.split('-')[-1]))]
    assert requests, run
    needed = {request['frameId'] for request in requests}
    states = {}
    trace = run/entry.get('trace', 'trace.jsonl')
    initial = None
    for line in trace.open():
        state = json.loads(line)
        if initial is None:
            initial = state
        if state['step'] in needed:
            states[state['step']] = state
    assert set(states) == needed
    assert initial['localization']['pose'] == [0, 0, 0]
    assert not initial['discovery']['suppliedMap'] and not initial['discovery']['worldPoseInput']
    teacher = VisibilityTeacher(Path(entry['environment']), initial['pose'], evaluator)
    mapper = module('native_training_mapper', mapper_path)
    captured = []

    def capture(known, blocked, pose, visits, candidates, distances):
        captured[:] = [(known, blocked, np.asarray(pose), visits, candidates.copy(), distances)]

    # Observe the existing full proposal pool without changing map/navigation code.
    source = mapper_path.read_text()
    marker = '    candidates.sort(key=lambda item: -item[0])'
    assert source.count(marker) == 1
    mapper.__dict__['capture_candidates'] = capture
    exec(compile(source.replace(marker,
        '    capture_candidates(known_free, blocked, pose, visits, candidates, distance)\n'+marker),
        str(mapper_path), 'exec'), mapper.__dict__)
    free = np.zeros((200, 200), np.int32)
    occupied = np.zeros_like(free)
    detail = np.zeros((1000, 1000), np.int16)
    height_seen = np.zeros(detail.shape, np.uint32)
    height_confirmed = np.zeros_like(height_seen)
    floor_detail = np.zeros(detail.shape, np.int32)
    visits = []
    rows = {key: [] for key in ('features', 'targets', 'raw_utility', 'groups', 'scenes', 'heuristic', 'gain')}
    images = set()
    manifests = {str(trace): sha256(trace), str(Path(entry['environment'])): sha256(entry['environment'])}
    group = group_start
    for index, request in enumerate(requests):
        assert set(request) == {'schema', 'frameId', 'newScan', 'pose', 'frames'}
        state = states[request['frameId']]
        assert request['pose'] == state['localization']['pose']
        for frame in request['frames']:
            assert set(frame) == {'rgb', 'frameId', 'calibration', 'robot'}
            path = Path(frame['rgb'])
            image = cv2.imread(str(run/'sensor'/f'frame-{frame["frameId"]}.png'))
            assert image is not None and path.read_bytes() == cv2.cvtColor(image, cv2.COLOR_BGR2RGB).tobytes()
            manifests[str(path)] = sha256(path)
            images.add(str(path))
        points, _ = mapper.cloud(request['frames'])
        mapper.update(free, occupied, points, request['pose'], detail, height_seen, height_confirmed, floor_detail)
        if request['newScan']:
            visits.append(request['pose'])
        safe, known, blocked, _ = mapper.navigation(free, occupied, request['pose'], visits)
        expected = run/'map/episode-0'/f'observed-{request["frameId"]}.bin'
        assert (~known).astype(np.uint8).tobytes() == expected.read_bytes(), ('map replay mismatch', expected)
        assert (~safe).astype(np.uint8).tobytes() == (expected.parent/f'safe-{request["frameId"]}.bin').read_bytes()
        manifests[str(expected)] = sha256(expected)
        if index % entry.get('stride', 1):
            continue
        known, blocked, pose, observed_visits, candidates, distances = captured[0]
        if len(candidates) < 2:
            continue
        # Cover the full proposal distribution; retain the baseline's best choices.
        if len(candidates) > maximum_candidates:
            rng = np.random.default_rng(int(entry['scene'])*100000+index)
            best = np.argsort([-c[0] for c in candidates], kind='stable')[:maximum_candidates//4]
            others = np.setdiff1d(np.arange(len(candidates)), best)
            selected = np.sort(np.r_[best, rng.choice(others, maximum_candidates-len(best), replace=False)])
            candidates = [candidates[i] for i in selected]
        actor = features(known, blocked, pose, observed_visits, candidates, distances)
        # Actual poses/reference geometry are used only after actor extraction.
        targets, raw = teacher.labels(known, pose, state['pose'], candidates, distances)
        heuristic = np.asarray([c[0] for c in candidates], np.float32)
        gain = np.asarray([c[0]+20*sum(math.exp(-float(np.sum((np.asarray(c[1][:2])-np.asarray(v[:2]))**2))/.12)
                                   for v in observed_visits) for c in candidates], np.float32)
        for key, values in dict(features=actor, targets=targets, raw_utility=raw,
                                groups=[group]*len(actor), scenes=[int(entry['scene'])]*len(actor),
                                heuristic=heuristic, gain=gain).items():
            rows[key].extend(values)
        group += 1
        if index % 20 == 0:
            print(json.dumps(dict(replaying=str(run), stereoPairs=index+1, decisions=group-group_start)), flush=True)
    receipt = dict(run=str(run), scene=entry['scene'], pairs=len(requests), matchedRawRGBImages=len(images),
                   mapsByteMatched=True, decisions=group-group_start, candidates=len(rows['features']))
    return rows, group, receipt, manifests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--max-candidates', type=int, default=192)
    args = parser.parse_args()
    cv2.setNumThreads(1)
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.workspace/'flex/vision'))
    evaluator = module('training_map_evaluator', args.workspace/'flex/scripts/benchmark-map.py')
    entries = json.loads(args.inputs.read_text())
    splits = {name: sorted({int(e['scene']) for e in entries if e['split'] == name}) for name in ('train', 'validation')}
    assert splits['train'] and splits['validation'] and not set(splits['train']) & set(splits['validation'])
    manifest = dict(schema='puppybot.native-frontier-data.v1', splits=splits, actorFeatures=FEATURE_NAMES,
        actorContainsReferenceGeometry=False, actorSource='Actual native wrist-RGB stereo replay; all observed/safe masks byte matched',
        teacher='Offline static reference: 1.3m full-circle geometric visibility per estimated route cost, 20cm endpoint risk; utility normalized per decision. Not counterfactual RGB or executed action outcomes.',
        candidateSampling=f'Full native pool, up to {args.max_candidates} examples per decision: one quarter top heuristic plus uniform others',
        files={}, replays=[], trainingSeed=7)
    source_manifest = {str(args.inputs): sha256(args.inputs), str(Path(__file__)): sha256(__file__)}
    started = time.monotonic()
    for name in splits:
        combined = None
        group = 0
        for entry in entries:
            if entry['split'] != name:
                continue
            mapper_path = args.workspace/'flex/vision/discovery-base.py'
            if not mapper_path.exists():
                mapper_path = args.workspace/'flex/vision/discovery.py'
            rows, group, receipt, sources = replay(entry, mapper_path, evaluator, group, args.max_candidates)
            if combined is None:
                combined = rows
            else:
                for key in combined:
                    combined[key].extend(rows[key])
            manifest['replays'].append(receipt)
            source_manifest.update(sources)
        data = {key: np.asarray(value, np.int32 if key in ('groups', 'scenes') else np.float32) for key, value in combined.items()}
        assert len(data['features']) and data['features'].shape[1] == len(FEATURE_NAMES)
        path = args.output/(name+'.npz')
        np.savez_compressed(path, **data)
        manifest['files'][name] = dict(path=path.name, sha256=sha256(path), scenes=len(splits[name]),
            decisions=len(np.unique(data['groups'])), candidates=len(data['features']))
    manifest['elapsedSeconds'] = time.monotonic()-started
    (args.output/'dataset-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    (args.output/'replay-source-manifest.json').write_text(json.dumps(source_manifest, indent=2)+'\n')
    print(json.dumps(manifest), flush=True)


if __name__ == '__main__':
    main()
