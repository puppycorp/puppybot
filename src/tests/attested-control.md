# Isolated actor-boundary instrumentation

`prepare-attested-control.py NEW_DIRECTORY` copies and hashes the Flex source,
patches only the copy, and compiles `control-attested` there. The generated
build is experimental; never overwrite the active control or use it to claim
held-out qualification. Preparation starts no simulator or GPU job.

The isolated build accepts the single-policy fetch chase run path. It rejects
the intervention modes checked by its hook. Each game writes a new
`actor-attestation.bin` immediately before the action is applied. Its record
contains the resized byte image, the exact float input buffer supplied to the
policy stream, the policy response, and the action used by the chase loop.
The file has a completion footer and requires every horizon step. At 84 by 84
with 128 recurrent values, the journal is 106,932 bytes per action, about
30.6 MiB for a 300-action game. Additional results, snapshots and logs also
consume space.

The recorded action is the policy's pre-step float pair. Control later
quantizes it to thousandths for the simulator command; the journal alone does
not authenticate a command received or applied by an actuator. The actor
footer is written before simulator shutdown and the argv footer before the
policy child is reaped. A complete journal therefore does not establish a
successful run: independently check the process exit status, summary and
child logs as well.

`argv.bin` records the control process's argument bytes and each child spawn's
argument bytes immediately before fork. It uses exclusive creation and a
completion footer. `audit-attested-argv.py` rejects an incomplete file and
returns base64-encoded argument bytes without shell or Unicode interpretation.
The child records are **exec intent**, not evidence that fork or exec succeeded.
The journal does not record child working directories or environment, and it
does not prove the loaded executable, shared libraries or GPU runtime identity.

For a finished game, run the existing
`datasets/visual-control/chase-v1/levels/audit-actor-attestation.py` against
the game journal and directory. Its checks cover actor normalization, prior
actions, recorded own-drive feedback, recurrent chain, final action and game
identity. Aggregated contact feedback is cross-checked against recorded
proprioception rather than an independently authenticated protocol header.
The carry cue comes from simulator task state. Neither auditor independently
authenticates the rendered camera frame, proves the model executed the recorded
outputs, attests every loaded binary, or protects against owner tampering.
The extra instrumentation has not been shown behaviorally equivalent to the
original build on a real GPU. No previous evaluation is retroactively attested.

`python3 -I flex/tests/attested-control-isolation.py` compiles the isolated
control and exercises its actual actor and argv boundaries using CPU-only stub
peers and an existing saved Level 5 observation. It checks the bytes received
by the policy stub against the actor journal and runs both auditors. Local Unix
socket access is required; the test starts neither the real simulator nor a
GPU process. It is not a real-policy replay or a substitute for a future
instrumented evaluation with independently reviewed inputs and runtime. The
saved observation fixture is required: the test fails if it is absent.
Persistent negative checks reject blackout, hide-carry, search-cue,
straight-bias, ensemble and chase-forward before spawning either peer.
