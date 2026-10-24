#!/usr/bin/env python3
"""Survey unmodified stock YOLO on the robot's single wrist RGB camera."""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, directory, name, expected):
    (directory/(name+'.command.json')).write_text(json.dumps(command, indent=2)+'\n')
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
    (directory/(name+'.stdout.log')).write_text(result.stdout)
    (directory/(name+'.stderr.log')).write_text(result.stderr)
    if result.returncode != expected:
        raise RuntimeError(f'{name} exited {result.returncode}; see {directory}')
    return json.loads(result.stdout.strip().splitlines()[-1])


def annotate(path, result):
    with Image.open(path) as source:
        image = source.convert('RGB')
    draw = ImageDraw.Draw(image)
    for detection in result['detections']:
        x1, y1, x2, y2 = detection['box']
        draw.rectangle((x1, y1, x2, y2), outline='#49ef88', width=3)
        label = f'{detection["label"]} {detection["confidence"]:.0%}'
        draw.text((max(0, min(x1, 640-len(label)*7)), max(0, y1-14)), label, fill='#49ef88', stroke_width=1, stroke_fill='black')
    return image


def contact_sheet(output, samples):
    width, height = 320, 280
    sheet = Image.new('RGB', (width*4, height*((len(samples)+3)//4)), '#10171e')
    draw = ImageDraw.Draw(sheet)
    for index, sample in enumerate(samples):
        x, y = index % 4*width, index//4*height
        with Image.open(output/sample['annotation']) as image:
            sheet.paste(image.resize((320, 240)), (x, y+40))
        draw.text((x+5, y+4), sample['name']+' / '+sample['camera'], fill='white')
        labels = Counter(d['label'] for d in sample['detections'])
        caption = ', '.join(f'{label} ({n})' for label, n in labels.items()) or 'NO DETECTION >= 25%'
        draw.text((x+5, y+21), caption[:49], fill='#66dda0' if labels else '#e5bb77')
    sheet.save(output/'contact-sheet.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='new evidence directory')
    parser.add_argument('--backend', choices=('auto', 'sass', 'cuda', 'hip', 'cpu'), default='auto')
    args = parser.parse_args()
    output = (args.output or ROOT/'build/flex/sim/stock-vision'/f'{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}').resolve()
    output.mkdir(parents=True, exist_ok=False)
    binary = ROOT/'build/flex/puppybot-sim'
    detector = ROOT/'build/flex/puppybot-vision'
    manifest = ROOT/'build/flex/vision/yolo26n/model.json'
    model = json.loads(manifest.read_text())
    definition = ROOT/'flex/sim/cases/house-blocks-into-box.json'
    case = json.loads(definition.read_text())
    # These are independently spawned camera fixtures, not a navigation route.
    # Fixture poses, collision maps, sidecars and object IDs never reach YOLO.
    poses = [('home', [0, 0, 0])]
    poses += [(f'coverage-{i:02}', pose) for i, pose in enumerate(case['navigation']['coverage'])]
    poses += [('sofa', [0.65, 1.25, math.pi/2]), ('living-plant', [2.48, 1.5, math.pi/2]),
              ('coffee-table', [1.35, -0.85, -math.pi/2]), ('dining-chair', [5.9, 0.05, -math.pi/2]),
              ('dining-plant', [6.85, 1.4, math.pi/2])]
    fixtures = [('ball-control', None), *poses]
    report = {
        'schema': 'puppybot.stock-vision-survey.v1',
        'model': model['id'], 'classes': model['classes'], 'confidence': model['confidence'],
        'weightsSha256': model['weightsSha256'], 'manifestSha256': digest(manifest),
        'simulatorSha256': digest(binary), 'detectorSha256': digest(detector),
        'environmentSha256': digest(ROOT/'build/flex/sim/environments/apartment/apartment.bin'),
        'robotSha256': digest(ROOT/'build/flex/sim/puppybot.bin'), 'caseSha256': digest(definition),
        'boundary': {'modelInput': 'unannotated-mounted-camera-rgb-only', 'allClasses': True,
                     'modelTrained': False, 'thresholdModified': False, 'controllerModified': False,
                     'test': 'stationary-perception-survey', 'autonomousNavigationTest': False,
                     'fixturePoseSentToModel': False, 'simulatorGeometrySentToModel': False},
        'samples': [],
    }
    for name, pose in fixtures:
        directory = output/name
        directory.mkdir()
        # Let the free-falling ball settle before the positive control image.
        command = [str(binary), '--hidden', '--steps', '50' if pose is None else '1', '--bind', '127.0.0.1:0',
                   '--no-camera-panels', '--no-tcp-view', '--no-detector-view', '--sensor-capture', str(directory/'sensor')]
        if pose is not None:
            command += ['--case', case['id'], '--spawn', json.dumps(pose)]
        state = run(command, directory, 'capture', 1 if pose is not None else 0)
        # A finite, one-step house fixture intentionally leaves the case unfinished.
        # Validate sensor provenance independently before passing just RGB onward.
        if state['physicsFault'] or state['blocked']:
            raise RuntimeError(f'invalid physical fixture: {name}')
        (directory/'fixture-state.json').write_text(json.dumps(state, indent=2)+'\n')
        for camera, view in (('tcp', 'tcp'),):
            image = directory/f'sensor.{camera}.png'
            calibration = json.loads(Path(str(image)+'.camera.json').read_text())
            if calibration['view'] != view or (calibration['width'], calibration['height']) != (640, 480):
                raise RuntimeError(f'incorrect sensor export: {image}')
            command = [str(detector), '--model', str(manifest), '--image', str(image),
                       '--kernel', str(ROOT/'build/flex/pup-kernels'), '--backend', args.backend]
            result = run(command, directory, 'yolo-'+camera, 0)
            if result['model']['weightsSha256'] != model['weightsSha256']:
                raise RuntimeError('detector checkpoint changed')
            (directory/f'{camera}.detections.json').write_text(json.dumps(result, indent=2)+'\n')
            annotation = directory/f'{camera}.annotated.png'
            annotate(image, result).save(annotation)
            report['samples'].append(dict(name=name, camera=camera, fixturePose=pose,
                image=str(image.relative_to(output)), imageSha256=digest(image),
                annotation=str(annotation.relative_to(output)), detections=result['detections'], backend=result['backend']))
        labels = [d['label'] for sample in report['samples'][-1:] for d in sample['detections']]
        print(f'{name}: '+(', '.join(labels) or 'no detections'), flush=True)
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    control = [d for s in report['samples'] if s['name'] == 'ball-control' and s['camera'] == 'tcp' for d in s['detections']]
    house = [s for s in report['samples'] if s['name'] != 'ball-control']
    report['summary'] = dict(houseImages=len(house), houseImagesWithDetections=sum(bool(s['detections']) for s in house),
        houseLabels=dict(Counter(d['label'] for s in house for d in s['detections'])),
        ballPositiveControl=any(d['label'] == 'sports ball' and d['confidence'] >= 0.5 for d in control),
        limitations=['Stationary snapshots; no navigation or landmark association evaluated',
                     'No ground-truth image boxes: detections are unverified model predictions, not accuracy scores',
                     'Existing wrist camera mount and simple native materials',
                     'This checkpoint has no LEGO or storage-box label',
                     'No conclusion about other stock checkpoints or real-camera generalization'])
    contact_sheet(output, report['samples'])
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['summary'], indent=2))
    print(output/'contact-sheet.png')
    return 0 if report['summary']['ballPositiveControl'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
