#!/usr/bin/env python3
"""Matched confirmation trial, using the existing search-fallback runner."""
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base = load('dock_search_runner', ROOT / 'experiments/physical-search-fallback-trial-v1/run.py')
builder = load('dock_trial_builder', ROOT / 'experiments/physical-dock-confirm-v1/build.py')
base.__file__ = str(HERE / 'run.py')
original_required = base.required


def check_build(build):
    build = Path(build); report = json.loads((build / 'build.json').read_text())
    archive = builder.ARCHIVE; original = json.loads((archive / 'build.json').read_text())
    if (report.get('schema') != 'puppybot.physical-dock-confirm-build.v1' or
            report.get('archiveReportSHA256') != base.sha(archive / 'build.json') or
            report.get('transformSHA256') != base.sha(builder.HERE / 'transform.py') or
            report.get('compilerSHA256') != original['compilerSHA256'] or
            base.sha(builder.COMPILER) != report['compilerSHA256']):
        raise ValueError('dock build provenance differs')
    if base.prepare.hashes(archive / 'source') != original['patchedSource'] or base.prepare.hashes(archive / 'build/flex/sim/library') != original['library']:
        raise ValueError('search archive changed')
    if base.sha(archive / 'client') != original['clientSHA256'] or base.sha(archive / 'simulator') != original['simulatorSHA256']:
        raise ValueError('search archive binaries changed')
    source = build / 'source'; current = base.prepare.hashes(source)
    library = build / 'build/flex/sim/library'; libhash = base.prepare.hashes(library)
    if current != report['source'] or libhash != report['library']:
        raise ValueError('dock build sources changed')
    for name, digest in original['library'].items():
        if name == 'lib/f64.flex':
            old = f'import "{archive / "source/core/words.flex"}";'
            new = f'import "{source / "core/words.flex"}";'
            expected = builder.transform.once((archive / 'build/flex/sim/library' / name).read_text(), old, new)
            if (library / name).read_text() != expected: raise ValueError('library adapter differs')
        elif libhash.get(name) != digest: raise ValueError('unrelated library changed')
    if set(libhash) != set(original['library']): raise ValueError('library inventory changed')
    dependencies = f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n'
    if (library.parent / 'dependencies.flex').read_text() != dependencies: raise ValueError('dependencies differ')
    paths = [archive / 'source/sim' / name for name in ('collect.flex', 'discovery.flex', 'main.flex')]
    changed = dict(zip(('sim/collect.flex', 'sim/discovery.flex', 'sim/main.flex'),
                       builder.transform.transform(*(path.read_text() for path in paths))))
    if set(current) != set(original['patchedSource']): raise ValueError('source inventory changed')
    for name, digest in original['patchedSource'].items():
        if name in changed:
            if (source / name).read_text() != changed[name]: raise ValueError('candidate transform differs')
        elif current[name] != digest: raise ValueError('unrelated source changed')
    for name in ('client', 'simulator'):
        expected = report[name + 'SHA256']
        if (base.sha(build / name) != expected or base.sha(build / ('baseline-' + name)) != expected or
                not os.access(build / name, os.X_OK) or not os.access(build / ('baseline-' + name), os.X_OK)):
            raise ValueError('binary changed or same-binary comparison lost')
    if report['clientSHA256'] != original['clientSHA256']: raise ValueError('search client changed')
    return report


def env_for(flag):
    return dict(PATH='/usr/bin:/bin', HOME=str(Path.home()), SDL_VIDEODRIVER='offscreen',
                LD_LIBRARY_PATH=str(ROOT / 'build/flex/rocm-runtime'),
                PUPPYBOT_PHYSICAL_NAV_LIMIT='90', PUPPYBOT_PHYSICAL_POLL_LIMIT='1499',
                PUPPYBOT_PHYSICAL_SEARCH_FALLBACK='1', PUPPYBOT_DOCK_CONFIRM=flag)


def required(root, build):
    return original_required(root, build) + [Path(__file__), HERE / 'audit.py', HERE / 'monitor.py',
        Path(builder.__file__), builder.HERE / 'transform.py',
        ROOT / 'experiments/physical-search-fallback-trial-v1/run.py',
        ROOT / 'experiments/physical-search-fallback-trial-v1/audit.py']


base.check_build = check_build
base.env_for = env_for
base.required = required
ARMS = base.ARMS
sha = base.sha
hidden = base.hidden
check_manifest = base.check_manifest
check_invocation = base.check_invocation
launch = base.launch


if __name__ == '__main__':
    raise SystemExit('Simulator launch disabled pending independent review and resource scheduling.')
