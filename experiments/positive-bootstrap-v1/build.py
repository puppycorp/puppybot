#!/usr/bin/env python3
"""Build an isolated snapshot-only executable with a compiled allowlist digest."""
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMPILER = ROOT / 'build/flex/control/compiler'
HOST = ROOT / 'flex/control/host.flex'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_hashes():
    root = ROOT / 'flex'
    paths = sorted(root.rglob('*.flex'))
    if not paths or any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError('invalid project source tree')
    return {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in paths}


def regular_single(path):
    path = Path(path)
    return not path.is_symlink() and path.is_file() and path.stat().st_nlink == 1


def verify(policy, output, recompile=False):
    policy, output = Path(policy), Path(output)
    if output.is_symlink() or not output.is_dir() or not regular_single(policy):
        raise ValueError('invalid bootstrap build or policy')
    receipt_path, source_path, binary = output / 'build.json', output / 'snapshot.flex', output / 'snapshot'
    if not all(regular_single(path) for path in (receipt_path, source_path, binary)):
        raise ValueError('bootstrap build artifact is not a single-link regular file')
    receipt = json.loads(receipt_path.read_text())
    if (receipt.get('schema') != 'puppybot.positive-bootstrap-build.v1' or
            receipt.get('allowlistSHA256') != sha(policy.read_bytes()) or
            receipt.get('templateSHA256') != sha((HERE / 'snapshot.flex').read_bytes()) or
            receipt.get('builderSHA256') != sha(Path(__file__).read_bytes()) or
            receipt.get('sourceSHA256') != sha(source_path.read_bytes()) or
            receipt.get('binarySHA256') != sha(binary.read_bytes()) or
            receipt.get('compilerSHA256') != sha(COMPILER.read_bytes()) or
            receipt.get('sourceFiles') != source_hashes()):
        raise ValueError('bootstrap build receipt differs')
    expected = (HERE / 'snapshot.flex').read_text().replace('@HOST@', str(HOST.resolve())).replace(
        '@POLICY_SHA@', receipt['allowlistSHA256'])
    if source_path.read_text() != expected:
        raise ValueError('bootstrap source differs from template')
    if recompile:
        with tempfile.TemporaryDirectory(prefix='puppy-positive-recompile-') as directory:
            rebuilt = Path(directory) / 'snapshot'
            result = subprocess.run([str(COMPILER), str(source_path), '-o', str(rebuilt)],
                                    cwd=ROOT, capture_output=True, text=True)
            if result.returncode or sha(rebuilt.read_bytes()) != receipt['binarySHA256']:
                raise ValueError('bootstrap recompilation differs')
    if receipt.get('sourceFiles') != source_hashes() or receipt.get('allowlistSHA256') != sha(policy.read_bytes()):
        raise ValueError('bootstrap inputs changed during verification')
    return receipt


def build(policy, output):
    policy, output = Path(policy), Path(output)
    if output.exists() or output.is_symlink() or not regular_single(policy):
        raise FileExistsError('preserve existing private build')
    parent = output.parent.resolve(strict=True)
    if not (parent.is_relative_to(ROOT) or parent.is_relative_to(Path('/tmp'))):
        raise ValueError('private build must be in the workspace or /tmp')
    policy_bytes = policy.read_bytes()
    value = json.loads(policy_bytes)
    if value.get('schema') != 'puppybot.positive-bootstrap.v1' or value.get('status') != 'synthetic_only':
        raise ValueError('synthetic bootstrap allowlist required')
    host = str(HOST.resolve())
    if not re.fullmatch(r'[A-Za-z0-9_./-]+', host):
        raise ValueError('unsafe host import path')
    template = (HERE / 'snapshot.flex').read_text()
    if template.count('@HOST@') != 1 or template.count('@POLICY_SHA@') != 1:
        raise ValueError('bootstrap source anchors differ')
    source = template.replace('@HOST@', host).replace('@POLICY_SHA@', sha(policy_bytes))
    compiler_before = sha(COMPILER.read_bytes())
    builder_before = sha(Path(__file__).read_bytes())
    sources_before = source_hashes()
    output.mkdir()
    source_path = output / 'snapshot.flex'
    source_path.write_text(source)
    binary = output / 'snapshot'
    result = subprocess.run([str(COMPILER), str(source_path), '-o', str(binary)],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    if (sha(COMPILER.read_bytes()) != compiler_before or sha(Path(__file__).read_bytes()) != builder_before or
            policy.read_bytes() != policy_bytes or
            source_hashes() != sources_before):
        raise ValueError('build input changed')
    receipt = {'schema': 'puppybot.positive-bootstrap-build.v1', 'status': 'synthetic_snapshot_only',
               'allowlistSHA256': sha(policy_bytes), 'templateSHA256': sha(template.encode()),
               'sourceSHA256': sha(source.encode()), 'compilerSHA256': compiler_before,
               'builderSHA256': builder_before,
               'binarySHA256': sha(binary.read_bytes()), 'sourceFiles': sources_before,
               'scope': 'local private snapshot executable only; no simulator or model execution'}
    with (output / 'build.json').open('x') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True); stream.write('\n')
    if verify(policy, output, recompile=True) != receipt:
        raise ValueError('private build readback differs')
    return receipt


if __name__ == '__main__':
    raise SystemExit('Disabled: synthetic fixtures require an explicit private caller.')
