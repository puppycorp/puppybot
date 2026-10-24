#!/usr/bin/env python3
"""Build a self-contained visual webpage from retained simulator stress evidence."""
import argparse
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT/'flex/sim/report'


def inline_json(value):
    return json.dumps(value, separators=(',', ':')).replace('<', '\\u003c').replace('&', '\\u0026')


def build(source, output):
    report = json.loads(source.read_text())
    if report.get('schema') != 'puppybot.stress-run.v1' or not report.get('runs'):
        raise ValueError('expected a nonempty puppybot.stress-run.v1 report')
    images, fixtures, sensor = {}, {}, {}
    for run in report['runs']:
        name = run['directory']
        if Path(name).name != name:
            raise ValueError('run directories must be direct children of the report directory')
        directory = source.parent/name
        for filename in ('initial.png', 'outcome.png'):
            payload = (directory/filename).read_bytes()
            if not payload.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('expected a native PNG screenshot')
            images[name+'/'+filename] = 'data:image/png;base64,'+base64.b64encode(payload).decode()
        fixtures[name] = json.loads((directory/'case.json').read_text())
        priorities = ('nonTargetSelection', 'multipleTargets', 'driveBlocked', 'lastCamera')
        selected = next((run['events'][key] for key in priorities if run['events'].get(key, {}).get('image')), None)
        if selected:
            filename = selected['image']
            if Path(filename).name != filename:
                raise ValueError('sensor filenames must be basenames')
            payload = (directory/'camera'/filename).read_bytes()
            if not payload.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('expected a native camera PNG')
            calibration = json.loads((directory/'camera'/(filename+'.camera.json')).read_text())
            perception = selected['perception']
            if calibration['frameId'] != perception['frameId'] or calibration['view'] != perception['view']:
                raise ValueError('camera evidence does not match its observation')
            images[name+'/sensor.png'] = 'data:image/png;base64,'+base64.b64encode(payload).decode()
            sensor[name] = dict(frame=perception['frameId'], view=perception['view'], chosen=perception['chosen'], detections=perception['detections'])
    checks = []
    regression = source.parent.parent/'catalog-regression/report.json'
    if regression.is_file():
        for case in json.loads(regression.read_text())['cases']:
            checks.append(dict(name=case['id'].replace('-', ' '), passed=case['passed'], detail=f'{case["inside"]}/{case["required"]} objects inside'))
    for filename, name, detail in (
        ('stress-core-regression.log', 'Simulator core', 'URDF pose, physical grasp/release, repeatability and API'),
        ('stress-infrastructure-final.log', 'Scenery and capacity', 'Solid props, invalid-input rejection and maximum scene capacity')):
        log = ROOT/'build/flex/sim'/filename
        if log.is_file() and 'checks passed' in log.read_text().lower():
            checks.append(dict(name=name, passed=True, detail=detail))
    page = (TEMPLATE/'index.html').read_text()
    page = page.replace('__STYLE__', (TEMPLATE/'style.css').read_text())
    page = page.replace('__SCRIPT__', (TEMPLATE/'report.js').read_text())
    page = page.replace('__PAYLOAD__', inline_json(dict(report=report, images=images, fixtures=fixtures, sensor=sensor, checks=checks)))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix+'.tmp')
    temporary.write_text(page)
    temporary.replace(output)
    print(f'{output}: {len(report["runs"])} runs, {len(images)} embedded images, {len(page.encode()):,} bytes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=ROOT/'build/flex/sim/stress/results/report.json')
    parser.add_argument('--output', type=Path, default=ROOT/'build/flex/sim/stress/highlights-site/dist/index.html')
    args = parser.parse_args()
    build(args.report.resolve(), args.output.resolve())


if __name__ == '__main__':
    main()
