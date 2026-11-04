#!/usr/bin/env python3
"""Post-run simulator-truth diagnostic for visual-stagnation.py output.

Usage: visual-stagnation-truth-audit.py RUN_DIRECTORY DETECTOR_REPORT_JSON

Simulator truth is read only here, after the image-only detector has run; it
must never be used as an actor input. This is a single-run diagnostic, not
evidence that a threshold generalizes or that robot recovery is safe.
"""
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    run, report_path = map(Path, sys.argv[1:]); report = json.loads(report_path.read_text())
    path = Path(__file__).with_name('visual-stagnation.py')
    spec = importlib.util.spec_from_file_location('visual_stagnation', path)
    detector = importlib.util.module_from_spec(spec); spec.loader.exec_module(detector)
    names, frames, speeds, ticks = detector.load(run)
    actor_digest = hashlib.sha256()
    for seq in names:
        for extension in ('rgb', 'action'):
            name = f'actor-{seq}.{extension}'
            actor_digest.update(name.encode() + b'\0' + bytes.fromhex(digest(run / 'actors' / name)))
    expected = {'actorFilesSHA256': actor_digest.hexdigest(), 'journalSHA256': digest(run / 'physical-agent.jsonl'),
                'detectorSHA256': digest(path)}
    if report.get('inputs') != expected or report.get('actorFrames') != len(frames):
        raise ValueError('detector report or actor inputs differ from current files')
    windows = report['windows']
    if len(windows) != len(frames) - detector.WINDOW + 1:
        raise ValueError('detector report does not cover all windows')
    for i, window in enumerate(windows):
        current = detector.classify(frames[i:i + detector.WINDOW], speeds[i:i + detector.WINDOW - 1], ticks[i:i + detector.WINDOW])
        current.update(startSequence=names[i], endSequence=names[i + detector.WINDOW - 1],
                       startTick=ticks[i], endTick=ticks[i + detector.WINDOW - 1])
        if current != window:
            raise ValueError('detector report differs from recomputed windows')
    result = json.loads((run / 'result.json').read_text()); trace = run / 'trace.jsonl'
    if digest(trace) != result['traceSHA256']:
        raise ValueError('simulator trace checksum mismatch')
    poses = {}
    with trace.open() as stream:
        for line in stream:
            state = json.loads(line); tick = state['totalSteps']
            pose = state['pose']
            if (type(tick) is not int or tick < 0 or not isinstance(pose, list) or len(pose) != 3 or
                    not all(type(value) in (int, float) and math.isfinite(value) for value in pose)):
                raise ValueError('invalid simulator tick or pose')
            if tick in poses:
                raise ValueError('duplicate simulator tick')
            poses[tick] = pose
    counts = {'stagnantAndStationary': 0, 'stagnantAndMoving': 0,
              'noEvidenceAndStationary': 0, 'noEvidenceAndMoving': 0, 'ineligible': 0}
    for window in windows:
        start, end = window['startTick'], window['endTick']
        try:
            segment = [poses[tick] for tick in range(start, end + 1)]
        except KeyError as e:
            raise ValueError('missing simulator tick in a detector window') from e
        p = segment[0]
        max_translation = max(math.dist(p[:2], q[:2]) for q in segment)
        max_rotation = max(abs((q[2] - p[2] + math.pi) % (2 * math.pi) - math.pi) for q in segment)
        stationary = max_translation < .01 and max_rotation < math.radians(2)
        if window['state'] == 'visual_stagnation':
            counts['stagnantAndStationary' if stationary else 'stagnantAndMoving'] += 1
        elif window['state'] == 'no_evidence':
            counts['noEvidenceAndStationary' if stationary else 'noEvidenceAndMoving'] += 1
        else:
            counts['ineligible'] += 1
    print(json.dumps({'status': 'diagnostic_only', 'traceSHA256': result['traceSHA256'],
                      'detectorInputs': expected, 'windows': len(windows), 'counts': counts,
                      'truthStationary': 'within 0.01 m and 2 degrees of the start for every tick in the window',
                      'scope': 'one simulator trace; thresholds fitted to this trace, not a generalization or safety result'}, indent=2))


if __name__ == '__main__':
    main()
