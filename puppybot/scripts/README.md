# PuppyBot scripts

Run one interactive Tinygrad V6 simulator episode from any working directory:

```sh
./scripts/run-tinygrad-v6-sim-episode.sh --seed 42
```

The launcher opens an OpenCV window containing the exact TCP camera frame used
for Tinygrad inference, with its detector overlay. The simulator stays
headless because this is an external policy window, not a simulator window.
Close the preview to stop drive/arm safely, stop the runtime cleanly, and write
an `episode-result.json` with outcome `operator-stopped`; an intentionally
stopped episode does not run the completion judge.

For CI, video recording, or a non-graphical shell, disable the window:

```sh
./scripts/run-tinygrad-v6-sim-episode.sh --seed 42 --no-preview
```

To save the full episode from the mounted TCP camera (rather than a short
pickup clip), use the headless recording command:

```sh
./scripts/run-tinygrad-v6-sim-episode.sh --seed 42 --no-preview --record-tcp-episode
```

It writes `continuous-video/continuous-tcp.mp4` with the model's boxes drawn
only after inference. The video is one local encoder stream of policy-consumed
TCP frames plus low-rate policy heartbeats during arm and bin travel, covering
SEARCH, approach, pickup, drive to the bin, and release without starting a
second simulator-side capture renderer.

The launcher clears an inherited `LD_LIBRARY_PATH` so it also works when run
from a Flatpak-hosted terminal such as Zed. This prevents Flatpak-private
libraries from being injected into host `mkdir`, Python, and Cargo processes.

It resolves the project-local `.venv` Tinygrad environment and V6 checkpoint itself,
then gives the episode runner a unique artifact path under `workdir/recordings/`.
Use `--artifacts PATH` only with a new path; the runner creates it and the
script never deletes artifacts.

Attach the detector to a simulator that you started separately. The runtime
may bind its UI/service to the LAN, but its TCP-camera routes inspect the
actual socket peer and serve frames only to loopback clients. The attach script
itself accepts only a loopback URL and never starts or stops that runtime:

```sh
./scripts/run-runtime.sh --sim
```

Plain `--sim` starts the checked-in bottle-to-bin scene (the same scene source
as the episode runner, with its seed-42 bottle placement), so no additional
scene argument is needed before attaching. The episode runner itself still
randomizes a private copy and does not reveal its sampled bottle pose to the
policy.

```sh
./scripts/attach-tinygrad-v6-detector.sh
```

It accepts only `http://127.0.0.1:PORT` or `http://localhost:PORT`, defaults to
the runtime API at `http://127.0.0.1:8080` (not the WGUI dashboard, normally
`http://127.0.0.1:8081`), uses the bottle-template bin at `(-0.52, 0.32)`, and
creates a unique artifact directory only after preflighting the TCP-camera
endpoint. A local attach works
with either `127.0.0.1` or `0.0.0.0` runtime binding because access is checked
against the actual TCP client, not the listener. It opens an OpenCV preview of the exact TCP camera frame used for
inference, with the detection box drawn only after inference. The OpenCV window
opens immediately with a connection/arm-setup status card, then switches to the
annotated exact TCP frames. Closing that window stops drive and arm commands
before the policy exits; it does not stop the simulator. The isolated Tinygrad environment includes the GUI-capable
`opencv-python` package (not `opencv-python-headless`). Use `--no-preview` for
a headless rate check:

```sh
./scripts/attach-tinygrad-v6-detector.sh \
  --no-preview --measure-tcp-rate-samples 20
```

Use `--bin-x` and `--bin-y` only when the separately launched scene places its
known bin somewhere other than the checked-in bottle template.

To check the preview, run the default attach command in a graphical desktop
session, verify that its frame matches the TCP camera and that the green box
matches the bottle, then close the preview window. The policy writes its stop
result to `policy-result.json`; the simulator remains running. In a headless
shell, use `--no-preview --measure-tcp-rate-samples 20` instead. A requested
preview without a desktop display fails before any autonomy API request.

Attach mode intentionally keeps scanning when no bottle is visible.  It cycles
the finite TCP search-arc presets until it obtains a stable three-frame bottle
lock, you close the preview (or press `q`/Esc), or a runtime/control request
fails.  Its command, TCP-detection, and search-cycle logs retain only their
most recent diagnostic events, so an unattended search does not grow artifacts
without bound.
