# L5 camera-frame replay attempts (4 Nov 2026)

A planned diagnostic compares the parent and five-prefix checkpoint on two
reused L5 selection scenes, retaining the actor frames missing from the lean
selection. It does not use held-out scenes or establish physical performance.
The launch attempts and their failure statuses are preserved:

- V1 stopped before any game because its launcher changed after the plan was
  frozen. A two-line failure-receipt hardening edit landed during the
  baseline. The source-pin check caught it; the outer supervisor exited 1
  without remaining descendants.
- V2 entered the first game but the policy reported no CUDA or HIP device.
  The sandbox hid `/dev/kfd` and `/dev/dri`; read-only inspection outside the
  sandbox found both host device nodes. No simulator game or actor frame was
  recorded. The failed attempt and both supervisor statuses are retained.
- V3 ran the first parent game with host GPU access and saved all 300 action
  rows and 301 actor-frame pairs. Its strict state comparison rejected the
  initial state, so the monitor retained a failure and did not proceed to the
  remaining games. It has no completion receipt and is not a passed capture.

Two independent read-only comparisons found V3's first game matched the
original at every saved action boundary: all actions, proprioception, task
events, and the final result match. The captured state adds a frame filename
where the lean run has null. Four rows also differ in the evaluation-only
maximum localization error by about 0.0000442 m. The captured per-tick trace
contains an intermediate-tick peak that the lean action-boundary snapshots
did not sample; independently reconstructing each run's cumulative maximum
from its own sampling cadence explains all four differences. All other saved
initial and decision state fields match exactly.

These checks do not show that the original lean run had identical actor
pixels or an identical intermediate trajectory. A new, pre-registered
recording-aware comparator may verify the expected frame names and derive
both maxima from the appropriate samples while comparing all other saved
state fields exactly. V3's original failed status must not be changed.
