# Native Pup detection

YOLO26n runs as a static **Pup graph**, with its pretrained weights kept in a
separate named FP32 checkpoint. Convolution, SiLU, pooling, attention, resizing,
the multi-scale detection head and box decoding all execute in native Flexscript.
The shared Pup runtime keeps intermediate tensors and weights on the selected GPU. The CPU backend executes
the same packed FP32 operations and is primarily a correctness/reference path.
No Torch, Python inference process, ONNX Runtime or external model server is used.

## Prepare and run

From the repository root:

```sh
./flex/scripts/prepare-yolo.sh
./flex/scripts/build.sh
./build/flex/puppybotgym detect \
    --model build/flex/vision/yolo26n/model.json \
    --image build/flex/vision/bus.jpg
./build/flex/puppybotgym serve
```

Open **http://localhost:8090/live**, or choose **Live camera test** from the
centred Workspace menu. Start camera requests browser permission, starts the
resident Pup worker, and displays each analyzed frame with its matching boxes.
Stop releases the camera and cancels frame submissions; the loaded model stays
cached until Gym exits. Hidden tabs and navigation also stop camera capture.

Device selection defaults to `auto`: direct SASS on NVIDIA SM75 (including the
RTX 2070), PTX/CUDA on other NVIDIA devices, HIP on compatible AMD devices, then CPU when no GPU
is available. Both the CLI and Gym accept `--backend auto|sass|cuda|hip|cpu`
and `--device N`. An explicit backend fails if it cannot initialize that device.
The same Pup graph and checkpoint are used for every backend.

The build emits reusable operation kernels under `build/flex/pup-kernels/`:
SM75 cubins, PTX, and HIP source. `--kernel DIRECTORY` on the detector or
`--vision-kernel DIRECTORY` on Gym selects another kernel directory. Building
requires no GPU. Native PNG/JPEG decoding uses `libpng16.so.16` /
`libturbojpeg.so.0`; checkpoint integrity uses `libcrypto.so.3`.

For a separate Flexscript dependency checkout, set `FLEXSCRIPT_ROOT` alongside
`FLEXSCRIPT_COMPILER`. The build generates absolute import adapters without
modifying that checkout. The dependency needs `pup_parse_inference` and the
shared `device.flex` API, plus `libs/ml/pup/gpu.flex` and its operation modules
from Flexscript branch `codex/gpu-inference-lowering` (commit `4777273`).
The local kernel and compiler files are adapters to those upstream modules.

The preparation script uses a local build-directory venv, ONNX and NumPy to
extract the official Ultralytics ONNX release into `.pup` plus weights. It checks
the release SHA256 and compares the imported graph with the checked-in source.
Python is preparation/validation tooling; the resulting executable and worker
load only the native checkpoint. The optional independent validator uses
tinygrad. Neither preparation nor validation requires Torch.

## Model boundary

The components are intentionally separate:

- `.pup` declares the architecture and tensor operations.
- `model.json` identifies the model, preprocessing dimensions, class labels,
  confidence threshold, decoder and checkpoint; SHA256 binds the graph and weights.
- `../ml/compile.flex` lowers the Pup tensor graph into a native model factory.
- `../ml/runtime.flex` builds the execution plan and selects the device backend.
- `../ml/kernels/ops.flex` supplies model-independent tensor operations.
- `backend.flex` validates the detector manifest and loads the checkpoint.
- `detect.flex` accepts RGB observations and emits `puppybot.detections.v1`.
- `worker.flex` keeps one loaded model resident for camera requests.

To use another compatible architecture, build with:

```sh
PUPPYBOT_DETECTOR_MODEL=/path/to/detector.pup ./flex/scripts/build.sh
./build/flex/puppybotgym serve --model /path/to/model.json
```

Each binary contains the selected graph factory. Switching architectures
currently requires rebuilding; replacing a compatible checkpoint does not.
The graph hash must match its manifest, and each weight's name, shape and payload
must match the graph. Missing, corrupt or incompatible models fail explicitly.
Only one configured model is exposed by the Live view; there is no model catalog
or training UI yet. Additional architectures can reuse the execution backend and
observation/result contract. A different output representation needs a decoder
adapter; the current decoder is explicit and never guesses a tensor layout.

The initial adapter requires one `[1,3,H,W]` RGB image input and one
`[1,4+classes,anchors]` output: input-pixel `x1,y1,x2,y2` followed by class scores.
Letterboxing uses RGB/255 and grey 114 padding. YOLO26's one-to-one head needs no
NMS; the host selects the top class/anchor scores, equivalent to its two-stage
top-k away from score ties. Other suppression modes are rejected. The file CLI
returns at most 300 detections, Live at most 100. Boxes are clipped to the source
image, and empty boxes are omitted.

Results contain the model ID and graph/checkpoint hashes, frame ID/time/size,
backend and preparation/inference times, then class ID, label, confidence and
`[x1,y1,x2,y2]` boxes in **source image pixels**. There are no depth estimates,
grasp coordinates, simulator identities or control commands. Frame times in Live
use the server's monotonic clock when the frame is received.

## Live transport

Monolith renders the page and handles rollout forms/SSE. A small browser media
bridge uses `getUserMedia`, captures an RGB image as JPEG, and submits one frame
at a time with the Monolith action token. Images adapt to a 48,000-byte bound;
the server checks Host, Origin, token and content type. Other HTTP APIs retain
their original request limits. One worker serves one inference at a time;
competing clients receive a busy response and retry without queuing old frames.

The worker runs as a separate child with parent-death cleanup. Gym polls its
socket without blocking rollout management. A worker failure returns an error,
reaps the process, and allows a fresh start. Live images and detection results
are not written to disk. Worker diagnostics go to the Gym data directory.
Explicit CLI output/debug tensor options write only to their requested paths.

The standalone worker accepts `--frame-bytes 48000..131072` for local
high-quality camera experiments. Its default stays 48,000 bytes; Gym retains
its own 48,000-byte request limit. Frame dimensions and decoder checks still
apply. This transport setting changes neither the checkpoint nor inference.

## Verification

`./flex/scripts/test.sh` includes a small independent numerical fixture covering
all inference operators and malformed graph/checkpoint rejection. GPU validation:

```sh
PUPPYBOT_TEST_BACKENDS="sass cuda auto" python3 flex/tests/vision.py
DEV=CPU XDG_CACHE_HOME="$PWD/build/flex/vision/cache" \
    build/flex/vision-env/bin/python -m flex.tests.yolo
```

The full-model validator compares **2,116,800 output values**, selected scores and
source-image boxes against tinygrad on positive, flipped and blank images. It
reads the same official weights through tinygrad's independent ONNX reader.
Raw artifacts and error reports stay under `build/flex/vision/`.

`flex/tests/gym-live-browser.cjs` exercises the native browser media path using a
test video as the camera, actual Pup detections, permission errors, Start/Stop,
navigation keyboard dismissal and mobile layouts. Set `GYM_URL`,
`PLAYWRIGHT_MODULE` and `CHROMIUM` as for the existing Gym browser suite. The test
uses the Y4M camera fixture generated by `prepare-yolo.sh` at
`build/flex/vision/camera.y4m`. `python3 flex/tests/live.py` additionally checks
the real API's token/origin/body bounds, large JPEGs, resident-worker memory,
responsiveness, worker crash/restart and shutdown cleanup. Both require a
compatible GPU and prepared assets; they are separate from the device-free suite.

This verifies implementation parity and browser integration, rather than
real-world pickup performance. Camera calibration, tracking, articulated physics,
training, grasp estimation and autonomous robot motion are separate next stages.

Upstream model: [Ultralytics YOLO26](https://docs.ultralytics.com/models/yolo26/),
[pinned official release](https://github.com/ultralytics/assets/releases/tag/v8.4.0).
The checkpoint carries Ultralytics' AGPL-3.0 / Enterprise licensing; provenance
and upstream licensing are retained in its generated manifest.

GPU launches are prepared once and captured into a resident device graph; each
frame replays that graph. Softmax reduces each row once, and bounded tensor
index division uses a reciprocal estimate with exact integer correction.
Normalization uses device reciprocal approximations; numerical validation uses
explicit tolerances rather than requiring bit identity across GPU vendors.
The CUDA/SASS paths are validated on RTX 2070. HIP artifacts are compiled here;
this NVIDIA host cannot provide AMD execution evidence.

The current upstream HIP module loader targets gfx1201. Other AMD architectures
need support in that shared adapter; automatic selection does not change this limit.
