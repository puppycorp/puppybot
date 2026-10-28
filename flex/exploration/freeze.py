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


def freeze(output, visual=False, synchronous_mapping=False):
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
    setup = 'configure_visual' if visual else 'configure_output'
    original = original.replace('import numpy as np\n',
        'import numpy as np\nfrom explorer_ranker import '+setup+', rerank_candidates\n'+
        ('cv2.setNumThreads(1)\n' if visual else ''))
    original = original.replace(marker,
        '    candidates = rerank_candidates(candidates, known_free, blocked, pose, visits, distance)\n'+marker)
    if visual:
        marker = "    points, metrics = cloud(request['frames'])\n"
        assert original.count(marker) == 1
        original = original.replace(marker, marker+'    configure_visual(directory, request, points)\n')
    else:
        original = original.replace('    state = directory/\'evidence.npz\'',
            '    configure_output(directory, request[\'frameId\'])\n    state = directory/\'evidence.npz\'')
    assert original.count(setup+'(directory,') == 1
    mapper.write_text(original)
    shutil.copyfile(ROOT/'flex/exploration/policy.py', mapper.parent/'explorer_policy.py')
    shutil.copyfile(ROOT/'flex/exploration'/('visual_runtime.py' if visual else 'runtime.py'), mapper.parent/'explorer_ranker.py')
    if visual:
        for name in ('visual.py', 'visual_policy.py', 'policy.py'):
            shutil.copyfile(ROOT/'flex/exploration'/name, mapper.parent/name)
    if synchronous_mapping:
        main = workspace/'flex/sim/main.flex'
        source = main.read_text()
        marker = '        if active && (!ps_paused || single) && '
        assert source.count(marker) == 1
        source = source.replace('global ps_robot = 0;', 'global ps_benchmark_mapping_wait = 0;\nglobal ps_robot = 0;')
        source = source.replace('ps_case_observation(b); ps_discovery_observation(b);',
            'pl_text(b, ",\\\"benchmarkMappingWaitMs\\\":"); pl_uint(b, ps_benchmark_mapping_wait); ps_case_observation(b); ps_discovery_observation(b);')
        source = source.replace('let frames = 0;\n', 'let frames = 0; let mapping_started = 0;\n')
        source = source.replace(marker,
            '        // Benchmark action time excludes stationary asynchronous mapping waits.\n'
            '        // Both policies use this scheduler; wall runtime still includes all inference.\n'
            '        let mapping_wait = 0;\n'
            '        if ps_discovery_enabled && ps_discovery_phase == 3 && ps_discovery_job && active && !ps_paused {\n'
            '            if !mapping_started { mapping_started = wall; } h_pump(ps_discovery_job, 1);\n'
            '            mapping_wait = load64(ps_discovery_job + 8) == -999 || load64(ps_discovery_job + 40) >= 0 || load64(ps_discovery_job + 48) >= 0;\n'
            '            if mapping_wait { if wall - ps_discovery_started > 15000 { ps_discovery_update(); } gui_delay(1); }\n'
            '        }\n'
            '        if !mapping_wait && mapping_started { ps_benchmark_mapping_wait = ps_benchmark_mapping_wait + wall - mapping_started; mapping_started = 0; }\n'
            '        if active && !mapping_wait && (!ps_paused || single) && ')
        main.write_text(source)
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
        privateRobotAsset=True, synchronousMapping=synchronous_mapping,
        actorChanges='Candidate ranking only; traversability and physics unchanged'), indent=2)+'\n')
    print(output, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--visual', action='store_true', help='install the private YOLO visual-memory ranker')
    parser.add_argument('--synchronous-mapping', action='store_true', help='exclude worker waits from simulation action time for both policies')
    args = parser.parse_args()
    freeze(args.output.resolve(), args.visual, args.synchronous_mapping)


if __name__ == '__main__':
    main()
