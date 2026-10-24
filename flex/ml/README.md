# Shared Pup execution

[YOLO26n benchmark results and implementation comparison](benchmark-results.md)
record the measured PTX, direct SASS, PyTorch and tinygrad configurations.

The detector uses this model-independent compilation and execution path:

```text
Pup source -> validated tensor graph -> generated native model factory
                                                   -> resident execution plan
Tensor operation source -> word IR -> SASS / PTX / HIP kernels
                                                   -> selected device
```

`codegen.flex` is a thin adapter to Flexscript's `libs/ml/pup/gpu.flex`.
The compiler modules in the Flexscript repository perform graph fusion and buffer
placement, shape specialization, index narrowing, shared-memory/register tiling
and device compilation. The shared operation and packing kernels also live
there; local `kernels/` files only adapt imports to this host's numeric ABI. The
build compiles it to `build/flex/pup-codegen` and invokes that executable for
both generic operations and specialized plans. No Python code generates kernels
in the build path. `codegen.py` and `scripts/build-kernels.py` remain compatibility
launchers for existing test/tool callers; the old Python implementation lives
under `flex/tests/` as an independent parity oracle.

```sh
build/flex/pup-compiler flex/ml/codegen.flex -o build/flex/pup-codegen
build/flex/pup-codegen build/flex/pup-graph.bin \
  --root "$PWD" --compiler "$PWD/build/flex/pup-compiler" \
  --output build/flex/pup-kernels --backend all
```

`--emit-only` writes sources and plans without compiling GPU artifacts. It is
used by `flex/tests/codegen.py` to compare every generated source, binary plan
and metadata field against the preserved oracle across scheduling options.
Python still prepares compiler/UI dependencies and runs comparison/tuning tools;
those are separate from native tensor lowering and inference.

`compile.flex` uses Flexscript's Pup parser and host lowering. Its output
contains the graph factory, named input bindings, and model source hash.
Weights remain a separate named FP32 checkpoint. Input names and the graph
are supplied by the model; the runtime contains no YOLO architecture or labels.

`runtime.flex` implements static tensor construction, checkpoint binding,
allocation, operation scheduling and resident graph replay through Flexscript's
shared `device.flex`. CPU execution uses the same operation definitions.
`vp_inputs` and `vp_outputs` expose all factory bindings; detector-specific
image and output-shape restrictions belong to `vision/detect.flex`.

`kernels/ops.flex` defines arithmetic, broadcasting, convolution, pooling,
permutation, concatenation/slicing, resizing, batched matrix multiplication,
sigmoid and softmax. `codegen.flex --generic-only` compiles operation families
through the word IR to direct SM75 SASS cubins, NVIDIA PTX and HIP source.
Separate entry points keep live register frames within the SASS register budget.
`kernels.json` records each artifact's target and SHA256.

Automatic device selection prefers SASS on SM75, CUDA/PTX on other NVIDIA
devices, HIP on compatible AMD devices, and CPU when neither GPU API reports a device. Explicit
selection is available with `--backend` and `--device` in the host applications.
SASS cubins load directly through the CUDA driver; PTX is JIT-compiled by the
driver, and HIP source is compiled by HIPRTC.

The GPU plan owns persistent tensors, modules and launch descriptors. It is
captured once and replayed for each inference. `describe.flex` exports the static
graph inventory; `codegen.flex` specializes kernels by shape, fuses single-consumer
convolution/SiLU chains, and tiles convolution and matrix products in shared
memory. Contiguous slices become views, and eligible concatenation operands
write directly into disjoint ranges of their destination. The inventory hash
binds the schedule to its graph. Generic operation
kernels remain available when no matching schedule exists. Softmax reduces a row
once; bounded index division uses a high-word multiply and exact correction.
Device reciprocal approximations in normalization are checked against independent
numerical references with stated tolerances.

FP32 tiles batch four independent global loads, use aligned shared-memory pairs,
and prefetch the next reduction operands while the current operands are used.
Output activations expose independent exponential/reciprocal requests while
preserving each output's arithmetic order. Complete output tiles omit bounds
checks. Use `--staging 0`, `--no-vector`, `--no-pipeline`, or
`--no-batch-epilogue` to measure those choices independently; `--tile TM,TN,TK,RM,RN`
sets a block/reduction/register tile. `--interior-stencil` additionally batches
loads for depthwise 3x3 interior pixels; padded boundaries retain the scalar path.
`--patch-tiles` aligns eligible 3x3 reductions to whole image patches.
`--unroll N` chooses the largest divisor of each reduction tile no larger than
N; zero fully unrolls the tile. This bounds kernel code size without changing
the accumulation order.

Build the generic profiler with
`build/flex/pup-compiler flex/ml/profile.flex -o build/flex/pup-profile`.
Run `build/flex/pup-profile BACKEND KERNELDIR WEIGHTS.bin WEIGHTS_SHA256 INPUT.bin`
with one resident FP32 input file per factory binding, in binding order. It warms
the graph for at least half a second, captures 32 repetitions per operation including preparation kernels,
and reports the minimum of three CUDA-event samples per invocation as JSONL.
The profiler uses the linked model factory and checkpoint; it has no detector
architecture, image dimensions, labels or decoder assumptions.

Add `--graph` before `BACKEND` to measure operations in model order. This
captures eight complete model executions with external CUDA timestamp events
around each operation, including preparation, and reports the minimum interval
per operation. Event instrumentation adds overhead; these measurements guide
selection and do not replace complete uninstrumented inference benchmarks.

`tune.py --backend sass|cuda --candidate DIRECTORY PROFILE --output DIRECTORY`
selects kernels per operation from measured plans. Repeat `--candidate` for other
plans; the first supplies the baseline and generic kernels. Profile records bind
the backend, complete plan and main/preparation kernel SHA256 hashes, so replacing
an artifact invalidates its old measurements. Graph fingerprints, numerical
modes, fusions and tensor placement must match. Selection requires a 5% gain by
default. `--allow-unbound-profiles` accepts older timing files explicitly. The
selected directory contains the chosen native artifacts and schedule; pass it
to `--kernel`. Per-operation timings guide selection; validate numerical output
and benchmark complete graph replay afterward.
Profiles from the isolated-operation and model-order methods cannot be mixed.

`codegen.flex --residual-fusion` fuses eligible additions into convolution or matrix
epilogues, after any fused activation. Both operands must have the full output
shape, the residual must be available before the producer, and the original
producer result must have one consumer and no separate output binding. Contiguous
reshape views preserve linear indexing. The runtime binds the extra pointer in
launch word seven and validates its dependency and element count.

To retain measured kernel choices, apply the same pass afterward:

```sh
python3 flex/ml/fuse.py build/flex/pup-graph.bin \
  --candidate SELECTED_DIRECTORY --output FUSED_DIRECTORY \
  --compiler build/flex/pup-compiler --backend sass
```

Use `--backend cuda` or `hip` for their selected plans. This pass preserves tensor
placement and launch geometry, recompiles only changed kernels, copies required
preparation kernels, and records its inputs and transformations in `fusion.json`.
It accepts FP32 plans. Fusion can increase register pressure, so compare the
complete graph before adopting it. Independent output/dependency regressions
are in `flex/tests/residual.py`.

`codegen.flex` also folds concatenations of adjacent views and places immutable
shared operands directly in a concat destination. All views, consumers and
output bindings follow the relocated storage. A tensor keeps one physical
destination when multiple joins compete. `--no-join-views` and
`--no-shared-placement` disable these transformations independently.

Apply placement to a measured plan without recompiling its selected kernels:

```sh
python3 flex/ml/compact.py build/flex/pup-graph.bin \
  --candidate FUSED_DIRECTORY --output COMPACT_DIRECTORY --backend sass
```

`compaction.json` records eliminated operations and avoided copy bytes. The pass
preserves kernel arithmetic and launch geometry; `flex/tests/joins.py` checks
shared outputs, competing destinations, alias chains and changing inputs
through repeated captured execution.

`search.py` confirms profile-guided substitutions using complete resident
inference. Supply repeated `--candidate DIRECTORY PROFILE` pairs, plus
`--backend`, `--output`, `--benchmark`, `--weights`, `--weights-sha256` and one
`--input` per binding. The first candidate is the baseline. Identical native
code and launch configurations are deduplicated. Each proposed replacement must
preserve every output byte and improve paired A/B/B/A median and p10 timing;
failed children and regressions restore the last accepted plan. `search.json`
records all trials. Per-operation gains alone do not imply a model speedup.

After numerical validation and whole-model measurement, install each backend's
selected FP32 plan into the default directory:

```sh
python3 flex/ml/install.py --candidate COMPACT_DIRECTORY \
  --output build/flex/pup-kernels --backend sass
```

Repeat with `--backend cuda` and its selected directory. Installation copies
content-hashed main and preparation artifacts, writes a receipt with SHA256
hashes, and atomically replaces `plan-BACKEND-FINGERPRINT.bin`. The runtime
prefers this backend-specific plan and falls back to the common plan when it is
absent. Profiles bind the actual loaded plan. Regenerating the graph removes
its installed backend-specific plans; revalidate and reinstall selected plans
after a rebuild. `flex/tests/installation.py` covers fallback, artifact identity
and rebuild invalidation.

`benchmark.flex` times 30 synchronized whole-model replays after at least ten
warmups and half a second of warmup. Its arguments supply a checkpoint, all
input bindings and an output file; it has no detector assumptions. Output tensors
are written in factory binding order after timing. `flex/scripts/benchmark-yolo.py`
uses this runner for the detector comparison and supplies the matching PyTorch
and tinygrad references. All implementations use the same warmup duration.

`codegen.flex --convolution im2col` optionally builds a FP32 input matrix before
the tiled convolution. The default is `implicit`; measure the optional path on
the target device before selecting it. Workspaces are limited to 2^24 elements.

The default is static FP32 inference with ranks up to four and at most 2^24
elements per tensor. `PUPPYBOT_MATH=fp32-tc ./flex/scripts/build.sh` selects an
optional CUDA tensor-core mode: FP32 inputs and outputs, three FP16 products
using high parts and scaled residuals, and FP32 accumulation. This is approximate
arithmetic, reported as `mathMode: "fp32-tc"`, and requires separate numerical
validation. It is experimental: current YOLO checks still find errors beyond
the accepted tolerances. Unsupported reduction sizes use FP32 kernels. Packing rejects
nonfinite values and values outside the finite FP16 range; rebuild in `fp32`
mode for those inputs. Conversion kernels and their checks are included in
resident inference timing.

The build applies `flex/compiler/gpu-inference.patch` to an isolated copy of
the dependency source and builds its own compiler, preserving that checkout.
The compiler adds native 32-bit indexing, packed-half selection, paired FP32
FMA, shared-memory word operations, scalar register compaction and PTX helper
inlining. Native 64-bit loads fold positive displacements into the instruction;
shared-memory forwarding compares both the base and displacement. Model parsing, the execution plan and
machine-code lowering remain separate, reusable stages. Dynamic shapes and
training are not implemented.

The upstream HIP module loader currently targets gfx1201; execution on other AMD
architectures requires extending that adapter. HIP execution is not tested on
the NVIDIA validation host.

The 2026-10-21 upstream migration was built and tested against the reviewed
Flexscript checkout `build/flex/launch/gpu-inference-review` at `4777273`
on branch `codex/gpu-inference-lowering` ([upstream PR](https://github.com/J45k4/flexscript/pull/1)).
Set `FLEXSCRIPT_ROOT` and `FLEXSCRIPT_LIB` to that checkout when reproducing it.
Use a clean dependency checkout when building or validating to avoid unrelated
local compiler and UI changes.
