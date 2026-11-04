#!/usr/bin/env python3
"""Build an isolated visual-stall controller with a contact-zero ablation."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
P = ROOT / 'build/flex/sim/levels-v2/pitch82'
ARCHIVE = P / 'l5-steering-hysteresis-build-v1'
BUILD = P / 'visual-stall-build-v1'
COMPILER = ROOT / 'build/flex/control/compiler'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


prior = load('visual_prior_builder', ROOT / 'experiments/l5-steering-hysteresis-v1/prepare.py')
transform = load('visual_trial_transform', ROOT / 'experiments/visual-exact-stall-v1/transform.py')
base = prior.base
VISUAL = ROOT / 'experiments/visual-exact-stall-v1/visual-stall.flex'
CONTACT = ROOT / 'experiments/contact-stop-v1/contact-stop.flex'


def transformed(original):
    one = transform.contact.replace_one
    chase, main = transform.transform((original / 'control/chase.flex').read_text(),
                                      (original / 'control/main.flex').read_text())
    env = (original / 'control/environment.flex').read_text()
    env = one(env, 'global ve_lean=0;', 'global ve_visual_trial_zero_contact=0;\nglobal ve_lean=0;')
    env = one(env, 've_contact=load64(header+24);vc_require(ve_contact==0 || ve_contact==1,"invalid contact feedback");',
              've_contact=load64(header+24);vc_require(ve_contact==0 || ve_contact==1,"invalid contact feedback");'
              'if ve_visual_trial_zero_contact {ve_contact=0;}')
    main = one(main, '        else if pl_equal(flag,"--visual-stall-stop") {',
               '        else if pl_equal(flag,"--visual-trial-zero-contact") {'
               'vc_require(!ve_visual_trial_zero_contact,"duplicate zero-contact ablation");ve_visual_trial_zero_contact=1;}\n'
               '        else if pl_equal(flag,"--visual-stall-stop") {')
    anchor = '    vc_require(!vw_visual_stop || (pl_equal(command,"run")'
    main = one(main, anchor,
               '    vc_require(!ve_visual_trial_zero_contact || (pl_equal(command,"run") && vw_fetch && vw_policy && '
               '!vw_contact_stop && !vw_chase_forward && !vw_ensemble_count && !vw_sample_actions && !vw_record_memory),'
               '"zero-contact ablation requires an isolated simulated fetch policy run");\n' + anchor)
    anchor = '    if vw_visual_stop {pl_text(b,",\\"visualStopReason\\":");'
    chase = one(chase, anchor,
                '    pl_text(b,",\\"visualContactAblated\\":");pj_bool_text(b,ve_visual_trial_zero_contact);\n' + anchor)
    return {'control/chase.flex': chase, 'control/main.flex': main, 'control/environment.flex': env}


def inputs():
    receipt = prior.verify()
    paths = (Path(__file__), Path(transform.__file__), Path(transform.contact.__file__), VISUAL, CONTACT, COMPILER)
    return {'archiveReceipt': base.sha(ARCHIVE / 'build.json'), 'archiveControl': receipt['controlSHA256'],
            'files': {str(path): base.sha(path) for path in paths}}


def verify(output=BUILD):
    output = Path(output); receipt = json.loads((output / 'build.json').read_text())
    if receipt.get('schema') != 'puppybot.visual-stall-build.v1' or receipt.get('inputs') != inputs():
        raise ValueError('build inputs changed')
    source = output / 'flex-source'; original = ARCHIVE / 'flex-source'
    old = base.hidden.supervisor.source_hashes(original); actual = base.hidden.supervisor.source_hashes(source)
    changes = transformed(original); extras = {'control/visual-stall.flex': VISUAL, 'control/contact-stop.flex': CONTACT}
    if set(actual) != set(old) | set(extras) or any(actual[n] != h for n, h in old.items() if n not in changes):
        raise ValueError('unrelated build source changed')
    if (any((source / name).read_text() != content for name, content in changes.items()) or
            any((source / name).read_bytes() != path.read_bytes() for name, path in extras.items()) or
            actual != receipt['source'] or base.sha(output / 'control') != receipt['controlSHA256']):
        raise ValueError('transformation or output differs')
    return receipt


def build(output=BUILD):
    """A separate low-priority, locked supervisor must own this build."""
    output = Path(output)
    if output.exists() or output.is_symlink(): raise FileExistsError('preserve existing output')
    pinned = inputs(); output.mkdir(); source = output / 'flex-source'
    shutil.copytree(ARCHIVE / 'flex-source', source, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name, content in transformed(ARCHIVE / 'flex-source').items(): (source / name).write_text(content)
    shutil.copyfile(VISUAL, source / 'control/visual-stall.flex')
    shutil.copyfile(CONTACT, source / 'control/contact-stop.flex')
    compiled = subprocess.run([str(COMPILER), str(source / 'control/main.flex'), '-o', str(output / 'control')],
                              cwd=ROOT, timeout=120, capture_output=True)
    if compiled.returncode: raise RuntimeError('controller compilation failed: ' + compiled.stderr.decode(errors='replace')[-2000:])
    if inputs() != pinned: raise ValueError('inputs changed during build')
    receipt = {'schema': 'puppybot.visual-stall-build.v1', 'inputs': pinned,
               'source': base.hidden.supervisor.source_hashes(source), 'controlSHA256': base.sha(output / 'control'),
               'scope': 'isolated simulator build; synthetic contact suppression is not physical-sensor parity'}
    with (output / 'build.json').open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2); stream.write('\n')
    if verify(output) != receipt: raise ValueError('build verification differs')
    return receipt


if __name__ == '__main__':
    raise SystemExit('Disabled; reviewed low-priority locked supervision is required.')
