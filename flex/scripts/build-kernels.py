#!/usr/bin/env python3
"""Compatibility launcher: reusable operation emission is native Flexscript."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'flex/ml'))
from codegen import native

if __name__=='__main__':
    compiler=None
    if '--compiler' in sys.argv:compiler=sys.argv[sys.argv.index('--compiler')+1]
    raise SystemExit(subprocess.call([str(native(compiler)),'--root',str(ROOT),'--generic-only',*sys.argv[1:]]))
