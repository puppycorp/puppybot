"""Resident FP32 YOLO26n inference, same sliced ONNX and input, synchronized samples."""
import argparse
from ctypes.util import find_library
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT/'build/flex/vision'
OUT = ROOT/'build/flex/benchmark'
WARMUP, RUNS = 10, 30
WARMUP_SECONDS = .5


def record(name, samples, output=None, **extra):
    if output is not None:
        np.asarray(output, dtype='<f4').tofile(OUT/f'{name}-output.bin')
    result = dict(name=name, samplesMs=samples, medianMs=float(np.median(samples)),
                  p10Ms=float(np.percentile(samples, 10)), p90Ms=float(np.percentile(samples, 90)), warmupIterationsMinimum=WARMUP,
                  warmupSecondsMinimum=WARMUP_SECONDS,
                  gpuStateAfterSamples=subprocess.check_output(['nvidia-smi','--query-gpu=pstate,clocks.sm,clocks.mem,temperature.gpu','--format=csv,noheader'],text=True).strip(), **extra)
    (OUT/f'{name}.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'samplesMs'}), flush=True)


def timed(run, sync):
    start=time.monotonic();count=0
    while count<WARMUP or time.monotonic()-start<WARMUP_SECONDS:
        run();sync();count+=1
    sync()
    samples = []
    for _ in range(RUNS):
        start = time.perf_counter_ns()
        run()
        sync()
        samples.append((time.perf_counter_ns()-start)/1e6)
    return samples


def tinygrad_bench():
    # tinygrad's library search omits custom ldconfig directories.
    if 'NVRTC_PATH' not in os.environ:
        name=find_library('nvrtc')
        if name:
            for line in subprocess.check_output(['ldconfig','-p'],text=True).splitlines():
                fields=line.split()
                if fields and fields[0]==name and '=>' in fields:
                    os.environ['NVRTC_PATH']=fields[-1];break
    os.environ.setdefault('CUDA_CC','CUDA')
    from tinygrad import Tensor, TinyJit, Device
    from tinygrad.nn.onnx import OnnxRunner
    runner = OnnxRunner(str(ASSETS/'tinygrad-reference.onnx'))
    x = Tensor(np.fromfile(ASSETS/'bus-input.bin', '<f4').reshape(1,3,640,640), device='CUDA').realize()
    @TinyJit
    def run(x):
        return next(iter(runner({'images':x}).values())).realize()
    samples = timed(lambda:run(x), Device['CUDA'].synchronize)
    record('tinygrad', samples, run(x).numpy(), version=importlib.metadata.version('tinygrad'),
           mode='CUDA '+type(Device['CUDA'].compiler).__name__+', TinyJit CUDA graph', kernelLaunches=len(run.captured.jit_cache), replayItems=len(run.jit_cache))


def torch_bench():
    import onnx
    import torch
    import torch.nn.functional as F
    from onnx import numpy_helper
    from onnx.helper import get_attribute_value
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = True
    model = onnx.load(ASSETS/'tinygrad-reference.onnx')
    constants = {v.name:numpy_helper.to_array(v).copy() for v in model.graph.initializer}
    tensors = {k:torch.from_numpy(v).cuda() for k,v in constants.items()}
    plan = []
    for node in model.graph.node:
        attrs = {a.name:get_attribute_value(a) for a in node.attribute}
        ins, outs, op = list(node.input), list(node.output), node.op_type
        a = attrs
        if op in ('Add','Sub','Mul') and all(k in constants for k in ins):
            fn = {'Add':np.add,'Sub':np.subtract,'Mul':np.multiply}[op]
            constants[outs[0]] = fn(*(constants[k] for k in ins))
            tensors[outs[0]] = torch.from_numpy(np.asarray(constants[outs[0]])).cuda()
            continue
        if op == 'Conv':
            p = a['pads']; assert p[:2] == p[2:]
            fn = lambda v,a=a: F.conv2d(*v,stride=a['strides'],padding=a['pads'][:2],dilation=a['dilations'],groups=a['group'])
        elif op == 'Sigmoid': fn = lambda v: v[0].sigmoid()
        elif op == 'Add': fn = lambda v:v[0]+v[1]
        elif op == 'Sub': fn = lambda v:v[0]-v[1]
        elif op == 'Mul': fn = lambda v:v[0]*v[1]
        elif op == 'MatMul': fn = lambda v:v[0]@v[1]
        elif op == 'Concat': fn = lambda v,a=a:torch.cat(v,dim=a['axis'])
        elif op == 'Transpose': fn = lambda v,a=a:v[0].permute(a['perm'])
        elif op == 'Softmax': fn = lambda v,a=a:torch.softmax(v[0],dim=a['axis'])
        elif op == 'MaxPool':
            assert a['pads'][:2] == a['pads'][2:]
            fn = lambda v,a=a:F.max_pool2d(v[0],a['kernel_shape'],a['strides'],a['pads'][:2],a['dilations'],bool(a['ceil_mode']))
        elif op == 'Reshape':
            shape = constants[ins[1]].tolist(); assert 0 not in shape
            fn = lambda v,shape=shape:v[0].reshape(shape); ins = ins[:1]
        elif op == 'Split':
            sizes = constants[ins[1]].tolist()
            fn = lambda v,sizes=sizes,a=a:torch.split(v[0],sizes,dim=a['axis']); ins = ins[:1]
        elif op == 'Resize':
            assert a['mode'] == b'nearest' and a['coordinate_transformation_mode'] == b'asymmetric' and a['nearest_mode'] == b'floor'
            scales = constants[ins[2]].tolist(); assert scales[:2] == [1,1]
            fn = lambda v,scales=scales:F.interpolate(v[0],scale_factor=scales[2:],mode='nearest'); ins = ins[:1]
        elif op == 'Slice':
            starts, ends = constants[ins[1]].tolist(), constants[ins[2]].tolist()
            axes = constants[ins[3]].tolist() if len(ins)>3 else list(range(len(starts)))
            steps = constants[ins[4]].tolist() if len(ins)>4 else [1]*len(starts)
            slices = [slice(None)]*(max(axes)+1)
            for axis,start,end,step in zip(axes,starts,ends,steps): slices[axis] = slice(start,end,step)
            fn = lambda v,slices=tuple(slices):v[0][slices]; ins = ins[:1]
        else: raise ValueError(op)
        plan.append((ins,outs,fn))
    x = torch.from_numpy(np.fromfile(ASSETS/'bus-input.bin','<f4').reshape(1,3,640,640)).cuda()
    def run():
        values = dict(tensors); values['images'] = x
        for ins,outs,fn in plan:
            result = fn([values[k] for k in ins])
            values.update(zip(outs, result if isinstance(result,tuple) else (result,)))
        return values[model.graph.output[0].name]
    with torch.inference_mode():
        # Warm cuDNN algorithm selection before graph capture.
        samples = timed(run, torch.cuda.synchronize)
        eager = run()
        record('pytorch-eager', samples, eager.cpu().numpy(), version=torch.__version__, mode='eager CUDA/cuDNN', cudnn=torch.backends.cudnn.version())
        torch.cuda.synchronize()
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph):
            output = run()
        samples = timed(graph.replay, torch.cuda.synchronize)
        record('pytorch-graph', samples, output.cpu().numpy(), version=torch.__version__, mode='CUDA graph, CUDA/cuDNN', cudnn=torch.backends.cudnn.version())


def native(backend):
    binary=ROOT/'build/flex/pup-benchmark'
    subprocess.run([str(ROOT/'build/flex/pup-compiler'),str(ROOT/'flex/ml/benchmark.flex'),'-o',str(binary)],check=True)
    weights=ASSETS/'yolo26n/weights.bin'
    sha=hashlib.sha256(weights.read_bytes()).hexdigest()
    output=OUT/f'flexscript-{backend}{os.environ.get("PUPPYBOT_BENCH_LABEL","")}-output.bin'
    kernels=Path(os.environ.get('PUPPYBOT_BENCH_KERNEL',str(ROOT/'build/flex/pup-kernels')))
    result = subprocess.run([str(binary),backend,str(kernels),
                             str(weights),sha,str(output),str(ASSETS/'bus-input.bin')],cwd=ROOT,check=True,capture_output=True,text=True)
    fingerprint=json.loads((kernels/'plan.json').read_text())['fingerprint']
    plan=kernels/f'plan-{backend}-{fingerprint}.bin'
    if not plan.exists():plan=kernels/f'plan-{fingerprint}.bin'
    record('flexscript-'+backend+os.environ.get('PUPPYBOT_BENCH_LABEL',''), [v/1e6 for v in json.loads(result.stdout)],mode='resident CUDA graph',
           kernelDirectory=str(kernels),planSha256=hashlib.sha256(plan.read_bytes()).hexdigest(),benchmarkSha256=hashlib.sha256(binary.read_bytes()).hexdigest())


def report():
    names = ['flexscript-sass','flexscript-cuda','tinygrad','pytorch-eager','pytorch-graph']
    baseline = np.fromfile(OUT/'pytorch-graph-output.bin','<f4').reshape(1,84,8400)
    results=[]
    for name in names:
        result=json.loads((OUT/f'{name}.json').read_text())
        actual=np.fromfile(OUT/f'{name}-output.bin','<f4').reshape(baseline.shape)
        assert np.isfinite(actual).all()
        np.testing.assert_allclose(actual[:,:4],baseline[:,:4],atol=.003,rtol=3e-5)
        np.testing.assert_allclose(actual[:,4:],baseline[:,4:],atol=3e-5,rtol=3e-4)
        result['boxMaxAbsoluteError']=float(abs(actual[:,:4]-baseline[:,:4]).max())
        result['scoreMaxAbsoluteError']=float(abs(actual[:,4:]-baseline[:,4:]).max())
        results.append(result)
    report=dict(workload='YOLO26n pre-TopK output [1,84,8400]', input='resident batch1 NCHW FP32 [1,3,640,640]',
                timing='synchronized wall time, inference only, no upload/readback/preprocessing/decoding',warmup=WARMUP,warmupSecondsMinimum=WARMUP_SECONDS,iterations=RUNS,
                hashes={name:hashlib.sha256((ASSETS/name).read_bytes()).hexdigest() for name in ['tinygrad-reference.onnx','bus-input.bin','yolo26n/weights.bin']},
                gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,driver_version,pstate,temperature.gpu,clocks.sm,clocks.mem,power.draw','--format=csv'],text=True),results=results)
    (OUT/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=['# YOLO26n GPU comparison','',report['input'],report['timing'], '', '| Runtime | Median ms | p10–p90 ms | Inference/s |', '|---|---:|---:|---:|']
    for r in results: lines.append(f"| {r['name']} | {r['medianMs']:.3f} | {r['p10Ms']:.3f}–{r['p90Ms']:.3f} | {1000/r['medianMs']:.1f} |")
    lines.extend(['',f'At least {WARMUP} warmups and {WARMUP_SECONDS} seconds, {RUNS} measurements per runtime. All 705,600 output values agree within validation tolerance against PyTorch.','',report['gpu']])
    (OUT/'results.md').write_text('\n'.join(lines)+'\n'); print('\n'.join(lines))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('backend',choices=['sass','cuda','tinygrad','torch','report']); args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.backend in ('sass','cuda'): native(args.backend)
    elif args.backend=='tinygrad': tinygrad_bench()
    elif args.backend=='torch': torch_bench()
    else: report()
