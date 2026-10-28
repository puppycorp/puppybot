# Physical starting-pose coverage

The two-scene pilot completed physically but its first approach failed the
unchanged RGB projection audit. A side1 retry of exactly the same scenes and
seeds passed both independent native data audits, covering227 commands and
2,858 physical motion increments. The fitting trip begins with four right
turns, directly exercising the early avoidance action missing from the original
fitting distribution. The rejected original attempt remains in
`build/flex/sim/start-pose-v1/pilot/`.

All36 new histories completed and passed independent native audits, covering
3,773 commands and48,314 physical motion increments. The accepted aggregate is
`build/flex/sim/start-pose-v1/artifacts/data132/data.bin`:132 complete histories,
104 fitting /28 validation,16,765 supervised frames and sequence length354.
Its991,755,104 bytes have SHA256:
`d709d3378a1241c34ec885e1cce131dfa9cc5984208032a031ed315a4ba70eff`.

All96 earlier histories were retained. `finalize.sh` checks exact source audit
hashes/ranges, every scene identity, teacher metadata and binary split counts;
native merges preserve every history and role, followed by a byte-identical
native repack. Negative coverage checks reject substituted source hashes and
changed split roles. Runtime, catalog, robot-asset and recipe hashes are
checked again before admission. `artifacts/coverage.json`, `dataset.exit=0`
and `finalize.exit=0` record acceptance.

A new20-epoch native model completed training under
`build/flex/sim/start-pose-v1/models/pose/`, starting from the same direct-action
epoch80 checkpoint as the mirror experiment. It uses batch2, learning rate
0.0001, seed107 and original sensor views. The fixed10/20 snapshots scored
1/8 and2/8 audited screen returns respectively; both remained0/4 in the hidden
layout. All16 screen audits and both exact native forward checks passed.
Neither snapshot qualified for full32 validation or reserved final tests, and
the retained policy is unchanged. See [results.json](results.json).

Contact-direction diagnostics found97 fitting frames of forward-motion contact
versus1,244 while reversing. All97 forward-contact targets reverse direction;
the validation split contains213 such cases. The new pure-teacher trips added
no contacts, so this recovery imbalance persists. It is a concrete next data
coverage target; the result does not establish its sole causal role.

The existing fitting layouts begin at headings−0.105 through+0.07 radians;
the two validation layouts begin at+0.105 and+0.14. Mirroring only extends the
fitting range to±0.105. The hidden validation layout also puts the initial
drive path near the box, while early fitting labels almost always go straight.
This is a plausible coverage gap, not proof of the sole failure cause.

`generate.flex` prepares32 new fitting scenes from existing fitting layouts0–5,
with headings spanning±0.28 radians, lateral offsets±0.06m and forward offsets
±0.04m. It copies actual environment bytes into new files and changes only the
24-byte initial-pose header. Walls, objects and camera/robot assets retain their
source definitions. Every source environment hash is checked again afterwards.
The original symlinked environments are never written. Four additional scenes
retain their original validation roles and bytes in layouts6/7. Final10/11 are
excluded.

Generated catalogs are preparation only. Every teacher trip still has to
complete physically and pass independent RGB/input/oracle-label/motion,
35cm proximity and docking checks. Reject and preserve failed recordings;
repair the same scene without dropping it or relaxing acceptance. The intended
collection uses dense oracle labels and zero student roll-in, so these teach
the initial obstacle-avoidance actions directly. Actor inputs remain actual
RGB and own feedback, with the reserved event field zero.

If all36 new histories pass, they can be merged with all96 accepted recovery
histories, preserving104 fitting /28 validation roles. A354-frame horizon
keeps the complete132-history dense aggregate below the native1GiB file limit;
no existing history needs to be removed or truncated. Training and autonomous
evaluation remain subsequent steps, not claims made by catalog generation.
