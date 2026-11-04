#!/usr/bin/env python3
"""Build a single copied simulator with selectable old and revised floor guards."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARCHIVE = ROOT / 'build/flex/sim/levels-v2/pitch82/dock-barrier-rendered-build-v1'
CURRENT = ROOT / 'flex/sim/navigation.flex'
TRANSFORM = CURRENT
COMPILER = ROOT / 'build/flex/control/compiler'
FLAG = 'PUPPYBOT_SIM_OBSERVED_FOOTPRINT_V2'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prior = load('footprint_prior_builder', ROOT / 'experiments/dock-barrier-rendered-v1/build.py')
sha = prior.sha
hashes = prior.hashes


def once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('unexpected source anchor')
    return source.replace(old, new, 1)


def function(source, name):
    start = source.index('fn ' + name + '(')
    end = source.index('\nfn ', start + 1)
    return source[start:end]


def transform(nav, main, current):
    old = function(nav, 'ps_nav_observed_clear')
    new = function(current, 'ps_nav_observed_clear')
    old_named = once(old, 'fn ps_nav_observed_clear(', 'fn ps_nav_observed_clear_legacy(')
    new_named = once(new, 'fn ps_nav_observed_clear(', 'fn ps_nav_observed_clear_revised(')
    nav = once(nav, 'global ps_nav_training_oracle = 0;',
               'global ps_nav_training_oracle = 0;\n// Simulator-only comparison; disabled by default.\nglobal ps_nav_observed_v2 = 0;')
    replacement = old_named + '\n' + new_named + '''
fn ps_nav_observed_clear(x, y, heading) {
    if ps_nav_observed_v2 { return ps_nav_observed_clear_revised(x, y, heading); }
    return ps_nav_observed_clear_legacy(x, y, heading);
}'''
    nav = once(nav, old, replacement)
    anchor = '    let worker_barrier = pl_environment(argc, argv, "PUPPYBOT_SIM_WORKER_BARRIER");'
    opt = '''    let observed_v2 = pl_environment(argc, argv, "PUPPYBOT_SIM_OBSERVED_FOOTPRINT_V2");
    if observed_v2 {
        if !pl_equal(observed_v2, "0") && !pl_equal(observed_v2, "1") { pl_print(2, "Invalid observed footprint option.\\n"); return 2; }
        ps_nav_observed_v2 = pl_equal(observed_v2, "1");
    }
'''
    return nav, once(main, anchor, opt + anchor)


def verify(output):
    output = Path(output).absolute()
    report = json.loads((output / 'build.json').read_text())
    origin = prior.verify(ARCHIVE)
    if (report.get('schema') != 'puppybot.observed-footprint-matched-build.v1' or
            report.get('archiveBuildSHA256') != sha(ARCHIVE / 'build.json') or
            report.get('compilerSHA256') != sha(COMPILER) or
            report.get('builderSHA256') != sha(Path(__file__)) or
            report.get('currentNavigationSHA256') != sha(CURRENT)):
        raise ValueError('builder, source, compiler or archive differs')
    source = output / 'source'; library = output / 'build/flex/sim/library'
    actual_source, actual_library = hashes(source), hashes(library)
    if actual_source != report['source'] or actual_library != report['library']:
        raise ValueError('source or library changed')
    expected_nav, expected_main = transform((ARCHIVE / 'source/sim/navigation.flex').read_text(),
                                            (ARCHIVE / 'source/sim/main.flex').read_text(), CURRENT.read_text())
    if (source / 'sim/navigation.flex').read_text() != expected_nav or (source / 'sim/main.flex').read_text() != expected_main:
        raise ValueError('selectable guard transform differs')
    if set(actual_source) != set(origin['source']):
        raise ValueError('source inventory differs')
    for name, digest in origin['source'].items():
        if name not in ('sim/navigation.flex', 'sim/main.flex') and actual_source[name] != digest:
            raise ValueError('unrelated source changed: ' + name)
    if set(actual_library) != set(origin['library']):
        raise ValueError('library inventory differs')
    for name, digest in origin['library'].items():
        if name == 'lib/f64.flex':
            expected = once((ARCHIVE / 'build/flex/sim/library' / name).read_text(),
                f'import "{ARCHIVE / "source/core/words.flex"}";',
                f'import "{source / "core/words.flex"}";')
            if (library / name).read_text() != expected: raise ValueError('adapter differs')
        elif actual_library[name] != digest:
            raise ValueError('unrelated library changed: ' + name)
    dependencies = f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n'
    if (library.parent / 'dependencies.flex').read_text() != dependencies: raise ValueError('dependencies differ')
    for name in ('client', 'simulator'):
        binary = output / name
        baseline = output / ('baseline-' + name)
        if (sha(binary) != report[name + 'SHA256'] or sha(baseline) != report[name + 'SHA256'] or
                not os.access(binary, os.X_OK) or not os.access(baseline, os.X_OK)):
            raise ValueError('same-binary comparison differs')
    if report['clientSHA256'] != origin['clientSHA256']: raise ValueError('client differs')
    return report


def build(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink(): raise FileExistsError('preserve existing output')
    original = prior.verify(ARCHIVE)
    pinned = {'archiveBuildSHA256': sha(ARCHIVE / 'build.json'), 'compilerSHA256': sha(COMPILER),
              'builderSHA256': sha(Path(__file__)), 'currentNavigationSHA256': sha(CURRENT)}
    output.mkdir(parents=False, exist_ok=False)
    source = output / 'source'; build_root = output / 'build'
    shutil.copytree(ARCHIVE / 'source', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(ARCHIVE / 'build', build_root, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    library = build_root / 'flex/sim/library'; adapter = library / 'lib/f64.flex'
    adapter.write_text(once(adapter.read_text(), f'import "{ARCHIVE / "source/core/words.flex"}";',
                            f'import "{source / "core/words.flex"}";'))
    (library.parent / 'dependencies.flex').write_text(
        f'import "{library / "libs/render.flex"}";\nimport "{library / "libs/physics/physics.flex"}";\n')
    nav, main = transform((source / 'sim/navigation.flex').read_text(), (source / 'sim/main.flex').read_text(), CURRENT.read_text())
    (source / 'sim/navigation.flex').write_text(nav); (source / 'sim/main.flex').write_text(main)
    source_hash, library_hash = hashes(source), hashes(library)
    shutil.copyfile(ARCHIVE / 'client', output / 'client'); (output / 'client').chmod(0o755)
    compiled = subprocess.run([str(COMPILER), str(source / 'sim/main.flex'), '-o', str(output / 'simulator')],
                              cwd=ROOT, timeout=120, capture_output=True, text=True)
    if compiled.returncode:
        raise RuntimeError(compiled.stdout + '\n' + compiled.stderr)
    (output / 'simulator').chmod(0o755)
    for name in ('client', 'simulator'):
        shutil.copyfile(output / name, output / ('baseline-' + name))
        (output / ('baseline-' + name)).chmod(0o755)
    if prior.verify(ARCHIVE) != original or any(sha(path) != pinned[key] for key, path in (
            ('archiveBuildSHA256', ARCHIVE / 'build.json'), ('compilerSHA256', COMPILER),
            ('builderSHA256', Path(__file__)), ('currentNavigationSHA256', CURRENT))):
        raise ValueError('inputs changed during build')
    if hashes(source) != source_hash or hashes(library) != library_hash: raise ValueError('build inputs changed')
    report = {'schema': 'puppybot.observed-footprint-matched-build.v1', **pinned,
              'source': source_hash, 'library': library_hash, 'clientSHA256': sha(output / 'client'),
              'simulatorSHA256': sha(output / 'simulator'),
              'scope': 'copied simulator build only; disabled and enabled arms require the same binary'}
    with (output / 'build.json').open('x') as stream: json.dump(report, stream, indent=2, sort_keys=True); stream.write('\n')
    if verify(output) != report: raise ValueError('build verification differs')
    return report


if __name__ == '__main__':
    raise SystemExit('Disabled; use a separately reviewed and supervised build.')
