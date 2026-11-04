# Stereo worker scheduling and experimental barrier (3 Nov 2026)

The two disabled controls in diary 89 first differ in their saved simulator
traces at tick 1,892, before the journal difference at tick 1,897. Both
submitted stereo frame 1,621 and entered discovery phase 3. The
candidate-disabled trace advances from that phase at tick 1,892; the baseline
advances at tick 1,895. Both report map frame 1,621 with 29 free and 5 safe
cells after the worker completes. The resulting arm command is therefore
issued at different simulated times even though the saved actor inputs match.
The traces identify a scheduling mechanism; they do not establish that it is
the only source of divergence.

The archived simulator increments its simulated clock in 20 ms ticks and polls
the asynchronous stereo subprocess from the discovery update. How many ticks
pass while the subprocess runs depends on host and worker scheduling. The
prototype at `experiments/discovery-worker-barrier-v1/` optionally waits for
that subprocess inside one simulated tick in non-realtime virtual physical-agent
mode, records worker completion tick and wall latency separately, and leaves
the existing output validation and failure path in place. It rejects external
serial, realtime, missing-agent and missing-fd configurations. Worker completion
is not a claim that the output was valid or applied.

CPU checks pass for mocked delays and failures, actual child processes at
different delays, malformed worker output through the transformed simulator's
discovery update, and simulator compilation and option guards, including an
open agent descriptor. A separate supervised CPU-only diagnostic replayed a
complete retained stereo request from the older west-tight scene with identical
input hashes and two deliberately different host delays. The real stereo
worker and simulator validator applied frame 369 at harness-initialized tick
370 in both runs,
with matching map/mask hashes and elapsed worker times of 996 and 1,991 ms.
That was one direct result-validation harness, not the dock scene or a search
episode. A separate read-only review verified the four map output hashes and
both supervisor records. The saved input receipt does not pin the compiler,
archived simulator source, transform, runtime libraries or exact launched
environment; it cannot independently attest the build, execution identity or
GPU nonuse. No rendered full stereo episode was run. The prototype is
unpromoted: its 15-second deadline is cooperative because the host pump and
cleanup may themselves block, and host assertions may terminate before the
normal failure path. A hard external process-group supervisor, resource limits
and explicit censoring are required before use. Waiting also removes worker
latency from simulated-time scoring, so results cannot be compared directly
with the earlier unbarriered experiments. These checks do not establish whole
episode determinism, physical safety, or a successful robot task.

Evidence: `build/flex/sim/levels-v2/pitch82/dock-survey-elevation-monitored-v1/trial/`
contains each control's `run/trace.jsonl`; the isolated prototype and its
CPU-only test command are documented in
`experiments/discovery-worker-barrier-v1/README.md`. Archived simulator sources
and saved experiment outputs were not modified. The separate diagnostic output
is `build/flex/sim/barrier-real-worker-cpu-v1/result.json`.
