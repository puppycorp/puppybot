# Rendered worker-barrier diagnostic

This is a simulator-only diagnostic on the existing selection case. It builds a
copy of the clearance/elevation simulator with the opt-in discovery worker
barrier. All three arms use the same simulator and client bytes, the barrier,
and the same diagnostic recording. The first two arms are controls; only the
third enables the higher wrist survey. The inherited audit checks the controls'
protocol, saved prefix, actor inputs, hashes, and trace endpoints. The additional
audit compares worker frame and completion ticks with validated map-frame
transitions. A mismatch, missing evidence, timeout, or failed guard is censored.

The barrier stops simulated ticks while a stereo worker completes. `lastWallMs`
measures worker submission-to-completion elapsed wall time, separately from
simulated time; the worker can also run before the barrier begins. Therefore
this experiment does not measure real-time or physical robot performance, and
cannot establish physical safety or a successful pickup. The 15-second worker
deadline is cooperative: host pumping or stopping can block, so external
process supervision remains necessary.

The saved-input manifest and monitor receipts pin sources, build, worker inputs,
model, and selection scene. The inherited guards require 36 GiB free before
starting, stop below 34 GiB during the run, and retain a 32 GiB final floor;
the GPU monitor requires a 30-second idle baseline and its existing VRAM
thresholds. Each arm has a 300-second external wall deadline. The trial worker
and outer monitor have 2700- and 3000-second limits, and the independent final
audit has a separate 900-second limit. The CPU build supervisor has a 900-second
limit and runs at reduced CPU and I/O priority. A deadline retains partial
evidence and does not imply a valid comparison.

On 2026-11-03, a disposable CPU build compiled and verified; changing one
baseline simulator byte was rejected. Three barrier-transform tests and five
synthetic audit tests passed. Static independent review of the four launch
wrappers found no further wiring blocker. This is not a rendered validation;
only an actual monitored run can show whether controls and map transitions match.

The following commands are for dedicated, separately scheduled Python
processes from the repository root. They fail if output paths already exist and
do not replace previous artifacts. Direct script entry points remain disabled.

```sh
python3 -I -c 'import importlib.util; p="experiments/dock-barrier-rendered-v1/build-supervisor.py"; s=importlib.util.spec_from_file_location("build_supervisor",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); raise SystemExit(m.launch())'
```

After a successful CPU build, run the rendered diagnostic with:

```sh
python3 -I -c 'import importlib.util,json; from pathlib import Path; p="experiments/dock-barrier-rendered-v1/monitor.py"; s=importlib.util.spec_from_file_location("monitor",p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); d=Path("build/flex/sim/levels-v2/pitch82"); i=d/"physical-hybrid-hidden-v1/inputs"; r=m.launch(d/"dock-barrier-rendered-monitored-v1",d/"dock-barrier-rendered-build-v1",i/"case.json",i/"environment.bin",i/"model"); print(json.dumps({k:r.get(k) for k in ("status","comparisonEligible","censorReason")}))'
```

Inspect the build monitor `result.json` before the rendered command. The
rendered monitor's `completion.json`, the trial's `audit.json`, and their
source pins and receipts describe the result; absent completion or a censored
comparison is not a pass. Neither command authorizes an external robot.
