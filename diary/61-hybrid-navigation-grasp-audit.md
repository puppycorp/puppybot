# 61. Hybrid navigation-to-grasp diagnostic (3 Nov 2026)

The separately versioned `experiments/hybrid-physical-eval-v1` wrapper stages a
single fixed training-selection scene for one heading epoch-8 arm. It uses the
existing simulated physical agent: recorded policy drive commands precede a
stopped RGB-detection handoff; the existing heuristic collector then attempts
capture, return and release. This is not the virtual-fetch scoring path and
not a learned grasp or return controller.

The offline auditor checks action-file/drive-echo consistency, image freshness,
protocol sequence, ownership, clock, stop echo, trace end at the stop tick,
and pinned inputs. It reruns the manipulation trace auditor. A simulated
completed delivery requires a nonzero recorded drive, a mathematically
nonzero truth navigation path, bilateral-contact capture, release over the
box, and the same target contained and settled through the end of the trace.
The path threshold is exactly `pathM > 0` metres: arbitrarily small numerical
motion qualifies, so it does not establish meaningful navigation or that the
motion caused detection. The scope is one simulator trial; camera-to-actor
pixels and policy execution are not independently authenticated. Simulator
truth is used offline only. No hardware or held-out result follows.

No handoff at the fixed 90-action limit, no nonzero drive, incomplete collector,
and terminal-without-settled-delivery are distinguished. Missing, malformed,
timed-out or unclean evidence is censored. The bounded 1,499 collector polls
are not evidence about eventual completion. The full Flex source snapshot is
captured during the trial rather than preregistered in advance.

Nine CPU test groups pass, including synthetic success and malformed outcomes;
independent review also passed. Those tests do not exercise a successful
end-to-end trial of this new wrapper. The previously saved 90-action hidden
navigation journal passes the protocol checks, but that earlier run did not
handoff or deliver. The visible collector success took zero policy actions and
is not a learned navigation-to-grasp success.

A separate disabled `monitor.py` is staged for a future reviewed GPU run. It
requires at least 36 GiB disk and the existing 30-second GPU baseline before
starting; checks 34 GiB disk and 2 GiB VRAM during the trial; and enforces
1,350-second worker and 1,500-second outer subreaper deadlines. A 32 GiB disk
floor is checked before publishing completion. Telemetry and disk logs are
retained. These sampled guards cannot prove another service was unaffected.
The completion audit requires GPU samples no more than 2.5 seconds apart throughout
and pairs each active disk sample with its corresponding GPU observation.
Independent CPU review passed the monitor's five test groups, including
detached-child cleanup and malformed or incomplete resource evidence. Neither
this wrapper nor the monitor has been run on a GPU. Their command-line
entrypoints remain disabled while the heading selection runs.
