# Simulator hybrid visual-stall search recovery (3 Nov 2026)

An isolated physical-hybrid simulator client now has an opt-in experiment
that can transfer to the existing camera/stereo search controller after five
identical validated actor images across four nonzero drive intervals. This
is a post-hoc threshold from the blocked trajectory in entry 75, not a
demonstrated recovery rate. It does not change the separate virtual-fetch
client or the physical robot code and is not an onboard single-policy
implementation.

The new client reuses the existing stopped search-only handoff. If a fresh
target appears during the handoff, it follows the existing target-handoff
path. Search ownership, target handoff and collector terminal responses do
not establish a pickup or delivery. The client reports whether recovery was
not triggered, search started unverified, a target handoff was unverified,
the transfer did not start, or the detector saw invalid input. A transfer
that does not start takes the existing simulated stop path. Malformed or
stale observations can still fail before the result or stop is confirmed.

The copied full client compiles. Twenty-one CPU socket tests passed with a
synthetic simulator and policy. Independent review repeated the first 19 and
reviewed the two later tests. They
cover early transfer, target appearance and disappearance during transfer,
normal changing images, explicit outcome reporting and disabled-path actor,
journal and result parity in the fixture. The last two checks cover prior
auditor identity and limits, and preservation of an existing trigger file.
Independent review covered their code; the complete 21-test suite passed
after a retry when automatic permission review initially timed out. The detector-level invalid-input
outcome is not independently exercised by a new hybrid fixture. A simulated
stop acknowledgment does not establish physical braking; the existing
collector uses simulated grasp and containment state. No rendered simulator,
real policy or physical robot was used in these tests.

Exact image equality can miss a noisy stationary camera or trigger on a
frozen or repeating view while moving. The collector's prior search trial
did not complete a delivery. This experiment cannot yet claim successful
recovery or measure false stops. An individual-run saved-protocol auditor now
reuses the earlier fallback checks and reconstructs early triggers from the
recorded actor images and an exclusively created trigger image. It rejects
missing or altered images, protocol evidence and contradictory outcomes;
detector-invalid outcomes are censored. This is local resized-image evidence,
not raw-camera or execution attestation. Trigger-image creation or writing
occurs before the transfer and can abort before a stop request. A future
rendered diagnostic still needs matched controls, frozen source identity
including transitive auditor helpers, resource monitoring and full failure
accounting. It must not count a search handoff as a completed fetch.

Artifact: `experiments/visual-search-recovery-v1/`.
