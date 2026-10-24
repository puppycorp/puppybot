# YOLO26n GPU comparison — 2026-10-20

RTX 2070 (SM75), batch 1, FP32 input `[1,3,640,640]`, output
`[1,84,8400]` before TopK. All implementations use the same model, weights and
input. These are saved measurements from separate runs on an active desktop.

Each run has at least 10 warmups and 0.5 seconds of warmup, followed by 30
synchronized wall-time samples. Timings cover resident inference, excluding
upload, readback, preprocessing and detection decoding. The p10–p90 column
describes sample variability within that run. Speedup uses the latest PyTorch
graph run as the reference; values above 1 mean faster.

| Implementation | Median ms | p10–p90 ms | Speedup vs PyTorch graph |
|---|---:|---:|---:|
| Flexscript PTX | 2.509 | 2.503–2.846 | 1.397× |
| Flexscript direct SASS | 3.457 | 3.440–3.823 | 1.014× |
| PyTorch CUDA graph | 3.505 | 3.498–3.874 | 1.000× |
| PyTorch eager | 6.135 | 5.925–8.682 | 0.571× |
| tinygrad TinyJit | 10.694 | 10.265–14.680 | 0.328× |

These Flexscript runs use the installed default kernel directory, with no
candidate-directory override. The preceding installed round measured PTX at
2.518 ms, SASS at 3.461 ms and PyTorch graph at 3.478 ms. Three rounds before
installation measured PTX at 2.496–2.499 ms, SASS at 3.430–3.435 ms and PyTorch
graph at 3.498–3.504 ms. Installation renames artifacts by content hash and
preserves their machine code. Recorded SM clocks were 1950–1965 MHz.

Both paths beat this PyTorch reference in all five rounds, and their medians
also beat the earlier 3.475 ms quieter reference. The latest PTX median reduces
latency by about 28% (1.40× throughput). The SASS margin is small: about 1.4% in
the latest round and 0.5% in the preceding installed round. Sample ranges
overlap, so these measurements establish a modest workload-specific SASS win,
with normal desktop variability.

| Implementation | Compilation and kernels | Execution and scope |
|---|---|---|
| Flexscript PTX | Pup graph → shape-specialized Flexscript operations → word IR → PTX → CUDA driver JIT to machine code | Persistent tensors and captured CUDA graph; shared-memory FP32 tiles, fused convolution/SiLU and residual additions, slice views, adjacent concat folding and shared destination placement. 134 main launches. No Torch in inference. |
| Flexscript direct SASS | Same Pup and operation path → word IR → native SM75 SASS cubins | CUDA driver loads native cubins; persistent tensors and captured graph. Measured reduction-loop choices and the same generic graph optimizations. 134 main launches. |
| PyTorch graph | Sliced ONNX operations mapped to PyTorch CUDA/cuDNN operations; cuDNN algorithm autotuning enabled | PyTorch 2.10.0+cu128, cuDNN 9.10.2, captured CUDA graph. FP32 with TF32 disabled; no `torch.compile` in this reference. |
| PyTorch eager | Same PyTorch operations and libraries as the graph reference | Python dispatch per inference, without CUDA graph replay. |
| tinygrad | ONNX reader → tinygrad CUDA/NVRTC kernels | tinygrad 0.12.0, CUDACompiler, TinyJit CUDA graph replay; 104 kernels and three replay items. Default tuning; no BEAM search. |

The last graph optimization removes 14 launches from the 148-launch residual
fusion plan and avoids copying 21,708,800 bytes per inference. It folds adjacent
views and lets immutable tensors with multiple consumers write into a shared
concat destination. Every consumer and output binding follows the relocated
storage. These transformations use graph dependencies and shapes, with no YOLO
node identities in the implementation.

The tuner now confirms profile-guided substitutions with paired whole-model
runs, requires identical output bytes, and rolls back regressions. Its latest
18 distinct SASS trials accepted no substitutions: the final gain came from
generic graph placement. Backend-specific plans are installed with content
hashes; 134 bound profile records per backend independently confirm the loaded
plan hash. Rebuilding a graph invalidates its installed tuned plans.

Both installed backends pass all 2,116,800 output comparisons and final
detections on positive, mirrored and blank images at the original tolerances.
The benchmark report also compares all 705,600 outputs against PyTorch.
Regression checks include 29,508 placement/replay checks, 3,868 residual checks,
7,185 small-network checks, and installer and tuner failure/rollback checks.
The experimental tensor-core approximation is excluded because it fails the
original final-confidence tolerance.

The operation generator and runtime are shared between models. Both NVIDIA
paths use the CUDA driver for allocation, module loading and graph execution.
Direct SASS currently targets SM75. HIP execution has no measurement on this
NVIDIA host. This comparison does not measure `torch.compile`, TensorRT, or a
BEAM-tuned tinygrad implementation.

[Raw samples, hashes, installed-plan receipts and validation](benchmark-results.json)
identify each table row and all repeat rounds. The harness is
`flex/scripts/benchmark-yolo.py`; the native runner is `flex/ml/benchmark.flex`.
The selected source plans are `build/flex/tile-sweep/placed-sass` and
`build/flex/tile-sweep/placed-cuda`, installed into `build/flex/pup-kernels`.
The reusable passes are `flex/ml/fuse.py`, `compact.py` and `install.py`;
[the shared runtime documentation](README.md) describes their workflow.

The generator was ported to native Flexscript on 2026-10-21:
[the upstream compiler](https://github.com/J45k4/flexscript/tree/codex/gpu-inference-lowering/libs/ml/pup/gpu)
now emits both operation families and specialized plans. PuppyBot imports it
through the thin `codegen.flex` adapter. Twelve option configurations reproduce every source,
binary plan and metadata field from the preserved Python test oracle exactly.
The installed artifacts used for the table above retain the same hashes.
The native path also passes independent GPU regressions and all 2,116,800 YOLO
output comparisons per backend. Python compatibility launchers no longer emit
kernel code.
