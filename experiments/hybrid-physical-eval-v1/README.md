# Hybrid simulated grasp-and-delivery diagnostic

This is a disabled, separate evaluation wrapper for the existing physical-agent
simulator path and the fixed epoch-8 heading package. No existing simulator,
client, training dataset, or held-out gate is changed. The wrapper must not be
run until it has independent review and a separately reviewed GPU/disk monitor;
its command-line entrypoint is deliberately disabled. It holds the shared
pitch82 lock, requires a new per-arm output directory and uses bounded
subreaper supervisors for the trial and post-run audit.

The fixed training-selection case starts with one target behind the robot. It
requires an initial RGB detector miss, recorded learned-policy navigation
actions and a stopped, RGB-gated handoff. A detector miss does not prove the
target is geometrically invisible, and action before detection does not prove
the action caused detection. The drive policy owns navigation only before the
handoff. The existing heuristic collector then owns navigation, grasp, return
and release. Actor contact and carry feedback are forced to zero in this
diagnostic interface; they are not physical gripper sensors.

The auditor rechecks the recorded actor action/drive correspondence, exact
case and simulator trace hashes, isolated source and dependency snapshots, and
the client input receipt. It reruns the independent manipulation audit on the
full trace. A `hybrid_simulated_delivery` requires at least one nonzero policy
drive before handoff and a nonzero simulator-truth navigation path, followed by bilateral-contact capture, a release over
the box and the same object still contained and settled at the end. Simulator
truth and body identity are used only by the offline audit, never supplied to
the actor. Recorded input/action files and command echoes do not independently
authenticate camera-to-actor resizing, policy execution, actual movement or
causation of the later detection. The separate truth-navigation trace reports
simulated movement after the run. The independent auditor's continuity and settling
rules can reject some physically plausible outcomes. A mathematically nonzero
path can be arbitrarily small; it is not a meaningful-distance or causal gate.
The orthogonal `motionStatus` distinguishes recorded zero commands, commanded
motion with zero recorded truth path, and a nonzero recorded truth path.

`no_handoff_within_navigation_limit`, `no_nonzero_policy_drive`, collector
incomplete, and collector terminal without a verified delivery are distinct
observations. A watchdog timeout, missing or inconsistent trace, missing source
or unclean supervisor is `censored`; a missing `outcome.json` is incomplete,
not success. A cutoff without delivery does not prove the collector could
never finish. The current fixed limits are 90 policy actions and 1,499 polls
of at most 20 simulator ticks, under the existing 300-second trial watchdog.

This can measure one **simulated hybrid** attempt. It is not a learned grasp or
learned return controller, a causal proof that movement produced the detection,
an independent held-out benchmark, or evidence of physical robot delivery.
The source and model hashes are not independent OS/runtime attestation. A
source snapshot is captured at trial time, rather than preregistering the full
source tree before launch. A
matched no-policy-action or alternative-policy control, repeated prespecified
scenes and a separate held-out protocol would be needed before comparative or
generalization claims.
