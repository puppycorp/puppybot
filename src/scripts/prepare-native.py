#!/usr/bin/env python3
"""Build a pinned native toolchain without changing the sibling checkout."""
import argparse
import fcntl
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REVISION = 'd98c05f3a7de693442c5ea532ce515524f9e206c'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--bootstrap', type=Path, required=True)
    args = parser.parse_args()
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    target = build / 'native-toolchain'
    expected = {'revision': REVISION, 'bootstrapSHA256': hashlib.sha256(args.bootstrap.read_bytes()).hexdigest()}
    with (build / 'native-toolchain.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        receipt = target / 'receipt.json'
        compiler = target / 'compiler-native'
        if receipt.is_file() and compiler.is_file():
            saved = json.loads(receipt.read_text())
            if all(saved.get(k) == v for k, v in expected.items()) and saved.get('compilerSHA256') == hashlib.sha256(compiler.read_bytes()).hexdigest():
                return
        archive = subprocess.run(['git', '-C', str(args.source.resolve()), 'archive', REVISION,
                                  'compiler', 'vm', 'lib', 'libs', 'scripts'], check=True, capture_output=True).stdout
        with tempfile.TemporaryDirectory(prefix='native-toolchain-', dir=build) as temporary:
            stage = Path(temporary)
            with tarfile.open(fileobj=io.BytesIO(archive)) as package:
                package.extractall(stage, filter='data')
            output = stage / 'compiler-native'
            subprocess.run([str(args.bootstrap.resolve()), str(stage / 'compiler/main.flex'), '-o', str(output)], check=True)
            expected['compilerSHA256'] = hashlib.sha256(output.read_bytes()).hexdigest()
            (stage / 'receipt.json').write_text(json.dumps(expected, indent=2) + '\n')
            if target.exists():
                shutil.rmtree(target)
            stage.rename(target)
        print(f'Prepared pinned native compiler and libraries: {REVISION}')


if __name__ == '__main__':
    main()
