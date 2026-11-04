# Private parent collector actor-boundary prototype

This is CPU-tested preparation only. It does not modify the active control
source, launch a policy or simulator, or authorize training. The frozen
`parent-route-collector-plan-v1` specifies an existing prebuilt control and
does not include this instrumentation. A real run therefore needs a new
pre-registered plan, independent review and a resource-monitored collector
supervisor before any GPU launch.

`transform.py` instruments a copied `chase.flex` only. In the fixed
policy-driven, teacher-labeled, map-recording fetch configuration, it writes
an actor journal *after* initial brick placement and the carry cue update,
after policy inference, but before the environment advances. The journal
records the pre-inference normalized input, resized image and recurrent
history, the returned action and recurrent output, and the applied action.
It uses `flex/control/actor-attestation.flex`; `parent-boundary.flex` writes
the contemporaneous teacher label and coverage-map bytes. The private copy
fails closed if noise, sampling, an ensemble, hidden carry, search cue or
other unsupported mode is requested. These are same-process snapshots; they
do not independently attest raw camera provenance, actor execution, or map
truth.

`audit.py` compares the full actor and map/label journals with the native
PVDATA01/PVMAP001 row bytes and saved decisions, checking tick and sequence
order, image normalization, recurrent continuity, action, teacher label,
map range, carry cue, data dimensions, masks, and first delivery. For each
fitting episode it requires at least one teacher-versus-parent action
difference within the first-delivery prefix; this conservative gate is not
applied to the excluded companion episodes. An independent saved
game/scene/event audit must run before this helper; the helper does not claim
the original prebuilt collector or its source identity has been validated.
The map comparison proves only that the dataset and sidecar agree, not that
the calculated map represents the world or is aligned to a verified camera.

`build.py` copies the current source to a fresh private path, applies only the
instrumentation, checks all unchanged copied files, compiles the full control
binary, and recompiles that source to verify identical binary bytes. The
result is not the earlier selection control binary; future replay must check
the original actions, states and events under a preregistered protocol. The
source is bound to the recorded compiler, but the compiler's broader execution
environment is not independently attested. The builder requires at least
38 GiB free and retains partial output on failure. Its direct CLI is disabled.

`python3 -B -I experiments/parent-route-actor-boundary-v1/test.py` compiles
the copied full control and a native synthetic probe. It tests row/feedback/
cue, action, map and teacher-label consistency, source and binary tampering,
truncation and ordering. It does not run a neural policy or rendered scene;
the fixture and private builder need independent review before use.
