#!/usr/bin/env python3
"""Render a completed stock-model experiment from its native scene captures."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='run directory containing trace.jsonl and frames/')
    args = parser.parse_args()
    root = args.directory.resolve()
    states = {s['totalSteps']: s for s in map(json.loads, (root/'trace.jsonl').open())}
    last = states[max(states)]
    if last['case']['phase'] not in ('passed', 'failed'):
        parser.error('the experiment must finish before rendering its result')
    render = root/'review'
    render.mkdir(exist_ok=False)
    scenes = sorted((p for p in (root/'frames').glob('scene-*.png') if re.fullmatch(r'scene-\d+\.png', p.name)),
                    key=lambda p: int(p.stem.split('-')[1]))
    entries = []
    for index, path in enumerate(scenes):
        meta = json.loads(Path(str(path)+'.camera.json').read_text())
        state = states[meta['frameId']]
        case, stock = state['case'], state['stockLandmarks']
        with Image.open(path) as image:
            canvas = Image.new('RGB', (1280, 864), '#10171e')
            canvas.paste(image, (0, 64))
        draw = ImageDraw.Draw(canvas)
        draw.text((14, 8), f'{case["id"].upper()} / {case["phase"].upper()} / PLACED {case["placed"]}/{case["required"]}', fill='white')
        draw.text((14, 27), f'Stock return: {stock["phase"]} | confirmations {stock["returnMatches"]}/3 | held: {state["gripper"]["held"]}', fill='#77efbd')
        draw.text((14, 45), f'Landmark gate {stock["minimumConfidence"]:.0%}; RGB LEGO/box detectors; known map outbound', fill='#c9cfd8')
        name = f'{index:04}.png'
        canvas.save(render/name)
        entries.append(dict(name=name, step=meta['frameId'], phase=case['phase'], placed=case['placed'], held=state['gripper']['held']))
    if not entries:
        parser.error('run has no native scene captures')
    # Keep the final independently judged outcome visible for two seconds.
    outcome = root/'outcome.png'
    if outcome.exists():
        with Image.open(outcome) as image:
            canvas = Image.new('RGB', (1280, 864), '#10171e')
            canvas.paste(image, (0, 64))
        draw = ImageDraw.Draw(canvas)
        draw.text((14, 8), f'{last["case"]["phase"].upper()} / {last["case"]["placed"]}/{last["case"]["required"]} PLACED', fill='white')
        draw.text((14, 29), last['case']['reason'], fill='#77efbd')
        draw.text((14, 47), 'Native rendered outcome; truth used for independent scoring', fill='#c9cfd8')
        canvas.save(render/'outcome.png')
        entries.append(dict(name='outcome.png', step=max(states), phase=last['case']['phase'], placed=last['case']['placed'], held=last['gripper']['held']))
    concat = []
    for index, entry in enumerate(entries):
        duration = max(0.04, (entries[index+1]['step']-entry['step'])*0.02) if index+1 < len(entries) else 2
        concat.extend(['file '+entry['name'], f'duration {duration:.4f}'])
    concat.append('file '+entries[-1]['name'])
    (render/'frames.txt').write_text('\n'.join(concat)+'\n')
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(render/'frames.txt'),
               '-vf', 'fps=25', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-movflags', '+faststart', str(root/'replay.mp4')]
    subprocess.run(command, check=True)
    indices = [0]
    for placed in range(last['case']['placed']+1):
        candidates = [i for i, e in enumerate(entries) if e['held'] and e['placed'] == placed and e['phase'] == 'navigating rooms']
        if candidates:
            indices.append(candidates[len(candidates)//2])
    indices.append(len(entries)-1)
    sheet = Image.new('RGB', (1280, 432*((len(indices)+1)//2)), '#10171e')
    for index, selected in enumerate(indices):
        with Image.open(render/entries[selected]['name']) as image:
            sheet.paste(image.resize((640, 432)), (index % 2*640, index//2*432))
    sheet.save(root/'highlights.png')
    print(root/'replay.mp4')


if __name__ == '__main__':
    main()
