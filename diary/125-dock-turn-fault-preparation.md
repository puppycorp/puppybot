# Prepared rendered dock-turn fault probe (4 Nov 2026)

The bounded dock-observation wait from [entry 123](123-dock-turn-wait-integration.md)
has an isolated six-arm fault probe under
`experiments/dock-turn-rendered-probe-v1/`. The private builds pair the
immediate-stop baseline and the current wait with no injected detection
loss, 10 simulated ticks of loss, or 60 ticks of loss. The injected loss
starts only at a settled yaw with a fresh, stable, unchanged box estimate;
missing that trigger is censored. It is simulated detector loss, not a claim
that a physical camera has failed or recovered.

All six complete simulator variants compile, and the native behavioral
probes pass. An independent review found and the author corrected audit gaps
for early restoration, missing suppressed samples, malformed supervisor
statuses, a delayed immediate stop, and an unpinned generated compiler input.
The six local audit fixture tests pass after those fixes. These probes use
stubbed sensing and actuation and do not demonstrate a rendered delivery.

The proposed scenario previously reached simulated release and settling,
but used an older source snapshot and no injected fault. The current source
and asynchronous mapping can take a different path, so even a clean rendered
run may never reach the eligible yaw. A separate serial execution adapter,
reviewed process and resource supervision, source/runtime/model pinning and
final inventory are still required. No GPU run or physical test has been
performed for this probe.
