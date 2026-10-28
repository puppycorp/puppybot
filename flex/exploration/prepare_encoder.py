#!/usr/bin/env python3
"""Build a separate native encoder from the existing pinned YOLO26n weights."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from policy import sha256

ROOT = Path(__file__).resolve().parents[2]


def prepare(output, size):
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT/'flex/vision/models/yolo26n.pup'
    text = source.read_text()
    marker = 'v77 = v75*v76\n'
    assert text.count(marker) == 1
    graph = text[:text.index(marker)+len(marker)]+'output v77\n'
    graph = graph.replace('[1,3,640,640]', f'[1,3,{size},{size}]')
    (output/'model.pup').write_text(graph)
    weights = ROOT/'build/flex/vision/yolo26n/weights.bin'
    shutil.copyfile(weights, output/'weights.bin')
    manifest = dict(schema='puppybot.encoder.v1', id='yolo26n-model6-v77',
        modelSha256=sha256(output/'model.pup'), weights=str(output/'weights.bin'),
        weightsSha256=sha256(weights), sourceGraphSha256=sha256(source),
        inputShape=[1, 3, size, size], outputShape=[1, 128, size//16, size//16],
        frozen=True, layer='model.6 output, stride 16; detection head excluded')
    (output/'model.json').write_text(json.dumps(manifest, indent=2)+'\n')
    generated = ROOT/'build/flex/yolo-encoder-model.flex'
    subprocess.run([str(ROOT/'build/flex/compile-pup'), str(output/'model.pup'), str(generated)], check=True, cwd=ROOT)
    compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler'))
    subprocess.run([compiler, str(ROOT/'flex/exploration/encoder.flex'), '-o', str(output/'encoder')], check=True, cwd=ROOT)
    for name, path in [('factory.flex', generated), ('encoder-source.flex', ROOT/'flex/exploration/encoder.flex')]:
        shutil.copyfile(path, output/name)
    manifest['binarySha256'] = sha256(output/'encoder')
    kernels = output/'kernels'
    kernels.mkdir()
    manifest['kernels'] = {}
    for stem in ('activation', 'binary', 'convolution', 'join'):
        for suffix in ('.cubin', '.ptx', '.hip'):
            name = stem+suffix
            path = ROOT/'build/flex/pup-kernels'/name
            shutil.copyfile(path, kernels/name)
            manifest['kernels'][name] = sha256(path)
    (output/'receipt.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(output, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--size', type=int, choices=(320, 640), default=320)
    args = parser.parse_args()
    prepare(args.output.resolve(), args.size)


if __name__ == '__main__':
    main()
