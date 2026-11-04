#!/usr/bin/env python3
"""Compile and run the isolated native recovery contract checks."""
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

with tempfile.TemporaryDirectory(prefix='puppy-recovery-contract-') as temp:
    binary = Path(temp) / 'test'
    subprocess.run([str(ROOT / 'build/flex/control/compiler'), str(HERE / 'test.flex'), '-o', str(binary)],
                   cwd=ROOT, check=True, timeout=120)
    subprocess.run([str(binary)], cwd=ROOT, check=True, timeout=15)
