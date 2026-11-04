# Dock survey recording diagnostic (simulator only)

This isolated transform adds opt-in recording to a copy of the previously
built dock-confirmation simulator. It does not edit the archived build or the
working simulator source. The direct build CLI is disabled; `build.py`'s
`build(output)` accepts a fresh path for a reviewed, supervised CPU build.
It verifies the archived input build, copies its source and libraries, builds
the entire simulator with the recorded compiler, and writes local checksums.

When a separately reviewed trial supplies `PUPPYBOT_DOCK_DIAG_DIRECTORY` as
an absolute path to a **new, existing, empty directory for that simulator
process**, each dock sample while carrying during phase 18 writes:

- `survey-<dock sample count>.rgb`: unmarked, top-left 640 by 480 RGB bytes;
- `survey-<dock sample count>.sensor.camera.json`: that frame's ID, capture
  time, intrinsic calibration and locally estimated camera basis.

The filenames use the monotonic dock-sample counter, not the frame ID. Camera
calibration comes from the same local pose and encoder inputs used by the
detector; it is not an independently measured camera pose. The saved trace
contains `case.dockVision.surveyDiagnostic.count`, `planCount`, and `writeErrors` only
when enabled. A write failure increments the count and leaves the controller's
existing observation, motion and failure behavior unchanged; missing or partial
diagnostic files must censor an image-based claim.

For every planned circular-viewpoint candidate, the process also writes
`search-<search number>-candidate-<index>.json`, containing the simulator
tick, estimated-frame goal, plan outcome, expansion count and reason code:

| Reason | Planner result |
| --- | --- |
| 0 | Plan returned success |
| 1 | Goal cell is outside the navigation grid |
| 2 | Goal cell is blocked or unknown in the navigation map |
| 3 | Full goal-configuration clearance check rejected it |
| 4 | The start configuration has no navigation index |
| 5 | No path was returned by the search, including any deadline outcome |
| 6 | The returned path exceeds its storage limit |

Reason 3 combines multiple clearance tests and does not distinguish unknown
floor, an observed obstacle, or the box margin. `expanded` is the planner's
recorded counter for the individual candidate, not proof of why a plan failed.
The files record local simulator state and intended observations; they are not
execution attestation, independent camera measurements, or physical safety
evidence. The operator must ensure separate directories per process: these
diagnostic filenames are not designed for multiple simulators to share.

With the environment variable absent, the recording hooks write no files and
the new trace fields are absent. The source transform preserves planner branch
order and outcomes, but full simulator parity has not been measured. With the
variable present, synchronous image and JSON writes can change real-time
scheduling and hence subsequent simulated trajectories. A useful rendered
diagnostic needs a dedicated monitored run with fresh paths, image and source
inventories, disk limits and explicit no-op/control comparisons. These outputs
must not be interpreted as a matched behavioral improvement.

Run the CPU checks with:

```
python3 -B -I experiments/dock-survey-diagnostic-v1/test.py
```

The tests build the complete copied simulator and exercise actual diagnostic
file serialization, disabled hooks and write failures with a native probe.
A second native probe runs the real planner's first four rejection branches
with mocked map and clearance primitives. Search exhaustion, a long path,
real camera capture and full rendered operation are not tested by these CPU
checks. No rendered run or physical test has been performed.
