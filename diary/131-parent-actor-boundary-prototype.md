# Parent collector actor-boundary prototype (4 Nov 2026)

An isolated collector source transform now records the actual policy input,
recurrent state, output and applied action at the pre-step boundary, after
initial placement and carry-cue selection. A companion same-boundary record
stores the teacher label and coverage-map bytes. The local auditor compares
these records with the fitting dataset rows, action journal, cue transitions,
recurrent continuity, validity masks and ordering. It requires a completed
first delivery and at least one teacher-versus-parent label difference
within that supervised prefix; differences only later do not qualify.

The complete private control copy compiles. Six CPU tests pass, including
native actor and map/label writers, action/cue/row alignment, corruption and
order rejection, deterministic compiler rebuild, source/binary tamper checks,
and the supervised-prefix negative case. An independent review found the
prefix-gate defect, confirmed the fix and reran the tests. Companion
validation episodes need a separate identity and saved-game audit; the
fitting-only helper deliberately requires first delivery and a label
difference.

The sidecar comparison is same-process consistency. It does not establish
camera provenance, correct map geometry, actor execution attestation, or
performance on new scenes. The frozen plan in entry 130 names a different,
unmodified collector binary and does not authorize silently substituting this
instrumented build. A new registered plan, monitored runner, rendered
collection and independent post-run audit remain necessary. No GPU or
collection run used this prototype. Artifact:
`experiments/parent-route-actor-boundary-v1/`.
