# Heading selection and the proposed robot goals

The fixed selection plan has two learned-policy arms on training layouts; it
does not contain a teacher. For each of standard and levels 1–5, the saved
pair audit records delivery counts and the fraction of 32 games with at least
one virtual delivery. It checks the existing short back-and-forth action
metric. The new per-game diagnostics additionally report:

* The first action whose saved simulator state has `consumedIndex >= 0`,
  checked against the reported reaches count. This is virtual consumption:
  `ps_seek_consume` matches a camera detection to an object within 35 cm and
  parks the simulated object below the world. It does not record or prove a
  physical gripper pickup. The older return-phase count remains a proxy.
* Level-4 doorway cases, one per placement with robot and brick on opposite
  sides of the saved scene's partition. A case is delivered if the next saved
  placement event is a delivery. An unfinished final opposite-side placement
  remains in the delivered-by-horizon denominator and is separately marked
  right-censored; cases placed at the final action have no time remaining and
  are counted separately. These are per-placement cases, not independent
  games; seed and layout matching does not force later placements to match.
* Mobile search loops using the existing 50-action wheel-odometry definition:
  at least 0.75 m travelled and ending within 0.4 m and 45 degrees of the
  start. Overlapping windows are unioned; the fraction uses search actions.
  The same calculation on simulator truth and their overlap are reported.
  Drift can create false flags, other loops are missed, and this is not a
  validated recovery signal or a held-out target pass. For a broader view,
  the audit also reports first-search path length and net displacement for
  odometry and simulator truth, measured between saved post-action states;
  large travel with little displacement is evidence to inspect, not a
  validated automatic loop classification.

A teacher comparison needs an additional separately reviewed and supervised
third arm on each fixed level, using the same seed, scene, initial robot and
brick positions, 300-action horizon, camera and simulator identity. The
current control parser selects the exploring fetch teacher with `collect
--chase --fetch --explore-teacher` (the `evaluate.sh` teacher path still needs
that explicit flag). Its per-game events and scores must be independently
audited and compared with each policy for the same initial placements; the
goal's rate comparison is total deliveries divided by 32 one-minute games per
level. Report game-level delivery reliability separately. If the teacher rate
is zero, report absolute rates and leave a rate ratio undefined; that alone
does not pass reliability. Subsequent placements can diverge with each arm's trajectory, so do
not claim matched target sequences or paired per-placement outcomes. Running
that teacher is not part of the two-arm plan and requires a frozen plan and
resource/supervision review before any GPU execution. The exploring teacher
can use scene wall geometry, so matching simulator settings and initial
placements does not give it the same information as the learned policy.
The collector also writes 24 PVDATA01 files, 50,908,832 bytes each (about
1.14 GiB total), in addition to traces and reports. The learned-policy run
path does not make these collection datasets; storage monitoring must account
for that extra space and retain partial outputs.

None of these training-layout measurements establishes independent held-out
performance, authenticated actor inputs, or a physical pickup and delivery.
