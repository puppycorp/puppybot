"""Compatibility entry point for the native Flexscript tensor compiler.

Kernel generation and graph lowering live in Flexscript libs/ml/pup/gpu/.
This adapter keeps existing Python validation and tuning callers working.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from plan import TARGETS, alias_root, fold_adjacent_joins, graph_fusions, graph_nodes, place_joins

ROOT = Path(__file__).resolve().parents[2]


def native(compiler=None):
    binary=ROOT/'build/flex/pup-codegen'
    binding=ROOT/'build/flex/pup-codegen.flex'
    metadata=ROOT/'build/flex/pup-compiler.json'
    dependency=Path(os.environ.get('FLEXSCRIPT_ROOT',json.loads(metadata.read_text())['source'] if metadata.exists() else ROOT.parent/'flexscript'))
    sources=[ROOT/'flex/ml/codegen.flex',binding,dependency/'libs/ml/pup/gpu.flex',*(dependency/'libs/ml/pup/gpu').glob('*.flex')]
    if not binary.exists() or any(path.stat().st_mtime_ns>binary.stat().st_mtime_ns for path in sources):
        compiler=compiler or os.environ.get('FLEXSCRIPT_COMPILER',str(ROOT/'build/flex/pup-compiler'))
        temporary=binary.with_name(binary.name+f'.tmp.{os.getpid()}')
        try:
            subprocess.run([str(compiler),str(sources[0]),'-o',str(temporary)],check=True)
            temporary.replace(binary)
        finally:
            temporary.unlink(missing_ok=True)
    return binary


def residual_epilogue(body, first):
    with tempfile.TemporaryDirectory(prefix='pup-residual-') as temporary:
        path=Path(temporary)/'body.flex';path.write_text(body)
        args=[str(native()),'--residual-body',str(path)]
        if first:args.append('--residual-first')
        return subprocess.run(args,check=True,capture_output=True,text=True).stdout


def compile_plan(inventory, output, compiler, backends, math_mode="fp32", convolution="implicit", tile=None, vector=True, staging=4, streaming=True, batch_epilogue=True, pipeline=True, interior_stencil=False, patch_tiles=False, unroll=0, packed_masks=False, residual_fusion=False, join_views=True, shared_placement=True):
    with tempfile.TemporaryDirectory(prefix='pup-codegen-') as temporary:
        path=Path(temporary)/'graph.bin';path.write_bytes(inventory)
        args=[str(native(compiler)),str(path),'--output',str(output),
              '--compiler',str(compiler),'--math',math_mode,'--convolution',convolution,
              '--staging',str(staging),'--unroll',str(unroll)]
        for flag,enabled in [('vector',vector),('streaming',streaming),('batch-epilogue',batch_epilogue),
                             ('pipeline',pipeline),('interior-stencil',interior_stencil),('patch-tiles',patch_tiles),
                             ('packed-masks',packed_masks),('residual-fusion',residual_fusion),
                             ('join-views',join_views),('shared-placement',shared_placement)]:
            args.append('--'+('' if enabled else 'no-')+flag)
        if tile is not None:args+=['--tile',','.join(map(str,tile))]
        if not backends:subprocess.run([*args,'--emit-only'],check=True)
        else:
            for backend in backends:subprocess.run([*args,'--backend',backend],check=True)


def main():
    compiler=None
    if '--compiler' in sys.argv:compiler=sys.argv[sys.argv.index('--compiler')+1]
    return subprocess.call([str(native(compiler)),*sys.argv[1:]],cwd=ROOT)


if __name__=='__main__':
    raise SystemExit(main())
