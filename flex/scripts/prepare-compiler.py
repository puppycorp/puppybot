#!/usr/bin/env python3
"""Build the GPU compiler changes in an isolated source copy; preserve upstream."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--bootstrap',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'build/flex/pup-compiler')
    args=parser.parse_args()
    source=args.source.resolve()
    stage=ROOT/'build/flex/pup-compiler-source'
    if source==stage or stage in source.parents:
        raise SystemExit("Choose the upstream compiler source, not the isolated build directory.")
    for name in ('compiler','vm','lib'):
        if (stage/name).exists(): shutil.rmtree(stage/name)
        shutil.copytree(source/name,stage/name,dirs_exist_ok=True)
    patch=ROOT/'flex/compiler/gpu-inference.patch'
    command=['patch','--batch','-p1','-d',str(stage),'-i',str(patch)]
    check=subprocess.run([*command,'--dry-run','--forward'],capture_output=True)
    if check.returncode==0:
        subprocess.run(command,check=True,capture_output=True)
    else:
        applied=subprocess.run([*command,'--dry-run','--reverse'],capture_output=True)
        if applied.returncode:
            raise SystemExit('GPU compiler patch does not match this Flexscript source; review the dependency revision.')
    temporary=args.output.with_suffix('.tmp')
    subprocess.run([str(args.bootstrap),str(stage/'compiler/main.flex'),'-o',str(temporary)],check=True)
    temporary.replace(args.output)
    manifest=dict(source=str(source),patchSha256=hashlib.sha256(patch.read_bytes()).hexdigest(),compilerSha256=hashlib.sha256(args.output.read_bytes()).hexdigest())
    (ROOT/'build/flex/pup-compiler.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Built isolated GPU compiler: {args.output}')


if __name__=='__main__':
    main()
