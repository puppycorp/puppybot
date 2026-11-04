# Matched teacher-label and parent-label training (4 Nov 2026)

Both registered arms completed one epoch from the same original parent using
fresh Adam optimizers, seed 7120000, batch size 2, the same learning rate,
carry cue, map supervision and mirror augmentation. The only intended data
difference was the 66 action labels in the two fitting prefixes described in
[entry 135](135-paired-parent-route-aggregates.md). Each reported 468
optimizer steps over 935 fitting histories, with 96 validation histories.
The epoch-1 checkpoint was fixed in advance, not chosen by validation.

The complete saved host batch journals are byte-identical: 468 batches, a
final batch of one history, identical episode order and seeded mirror masks.
The control and treatment epoch-1 weight SHA-256 values are respectively
`f78cd4346b42e7318e8b7252709b3e9a74fa31eca13e8ab6cc3c4a786172648d` and
`37dc95406fb3c81590d4f1c83fd0bf2327a740e6c1d86943284c7bc83e2b6036`.
Their first gradient files are identical, consistent with the first full-run
batch not containing the changed labels; the separate one-update smoke in
entry 137 selected a changed-label episode and observed different actor-bias
gradients. Finite losses, gradients and changed weights do not establish
which policy performs better.

The monitored run and independent post-terminal saved-output audit both
passed. The independent review reconstructed both model and schedule
reports, checked 154 inventory files, current inputs, supervisor/guardian
receipts and resource telemetry; it did not repeat the full prior ancestry
traversal already performed by the guarded final checker. Host batch-send
records do not independently attest GPU consumption or execution. Across
1,110 guardian samples minimum free disk was 45,717,852,160 bytes and minimum
free GPU memory was 9,226,346,496 bytes; sampling does not prove exclusivity.
The completion receipt SHA-256 is
`567cdbeaa77cf65e0df09d69f12771f8100dcab71e15f59bdb8ae0aa3fe3b21f`;
the final-result SHA-256 is
`f4711c4f1d922c5c79e3c263feb23af8e42475ed8d86a624fca734009dd973a1`.

Artifacts are under
`build/flex/sim/levels-v2/pitch82/parent-route-full-pair-v1/`. Both models
remain diagnostic candidates: no new-selection or held-out evaluation, model
promotion or physical robot test follows from training completion.
