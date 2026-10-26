#!/usr/bin/env python3
"""Freeze a private native explorer and its mapper for controlled experiments."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from policy import sha256

ROOT = Path(__file__).resolve().parents[2]


def freeze(output):
    output.mkdir(parents=True, exist_ok=False)
    workspace = output/'workspace'
    shutil.copytree(ROOT/'flex', workspace/'flex', ignore=shutil.ignore_patterns('__pycache__'))
    target = workspace/'build/flex/sim'
    target.mkdir(parents=True)
    shutil.copytree(ROOT/'build/flex/sim/library', target/'library')
    for name in ('dependencies.flex', 'dependencies.json', 'puppybot.bin'):
        shutil.copyfile(ROOT/'build/flex/sim'/name, target/name)
    # Compiler adapters contain absolute imports; retain an entirely private copy.
    for path in workspace.rglob('*.flex'):
        path.write_text(path.read_text().replace(str(ROOT)+'/', str(workspace)+'/'))
    mapper = workspace/'flex/vision/discovery.py'
    original = mapper.read_text()
    (mapper.parent/'discovery-base.py').write_text(original)
    marker = '    candidates.sort(key=lambda item: -item[0])'
    assert original.count(marker) == 1
    original = original.replace('import numpy as np\n',
        'import numpy as np\nfrom explorer_ranker import configure_output, rerank_candidates\n')
    original = original.replace(marker,
        '    candidates = rerank_candidates(candidates, known_free, blocked, pose, visits, distance)\n'+marker)
    original = original.replace('    state = directory/\'evidence.npz\'',
        '    configure_output(directory, request[\'frameId\'])\n    state = directory/\'evidence.npz\'')
    assert original.count('configure_output(directory,') == 1
    mapper.write_text(original)
    shutil.copyfile(ROOT/'flex/exploration/policy.py', mapper.parent/'explorer_policy.py')
    shutil.copyfile(ROOT/'flex/exploration/runtime.py', mapper.parent/'explorer_ranker.py')
    compiler = os.environ.get('FLEXSCRIPT_COMPILER', str(ROOT/'build/flex/pup-compiler'))
    with (output/'build.log').open('w') as log:
        subprocess.run([compiler, str(workspace/'flex/sim/main.flex'), '-o', str(output/'controller')],
            cwd=workspace, stdout=log, stderr=subprocess.STDOUT, check=True)
    sources = {str(path): sha256(path) for path in workspace.rglob('*') if path.is_file() and '__pycache__' not in str(path)}
    sources[str(output/'controller')] = sha256(output/'controller')
    (output/'frozen-source-manifest.json').write_text(json.dumps(sources, indent=2)+'\n')
    (output/'freeze-receipt.json').write_text(json.dumps(dict(workspace=str(workspace),
        binarySHA256=sha256(output/'controller'), mapperBaseSHA256=sha256(mapper.parent/'discovery-base.py'),
        sourceManifestSHA256=sha256(output/'frozen-source-manifest.json'), files=len(sources),
        privateRobotAsset=True, actorChanges='Candidate ranking only; traversability and physics unchanged'), indent=2)+'\n')
    print(output, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    freeze(args.output.resolve())


if __name__ == '__main__':
    main()
