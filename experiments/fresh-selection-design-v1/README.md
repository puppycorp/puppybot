# Prospective fresh five-level selection design

This is a **design and CPU-only preparation**, not a registered experiment.
It creates no real scenes, manifests, models or games. In particular, the
held-out catalog must not be generated or used here while its native ingestion
guard remains unwired. The `selection-role-prototype-v1` preparation API
currently requires a real pinned held-out manifest; that manifest does not
exist. Do not fabricate one or treat a synthetic test manifest as protection.

The fixed design is 32 games on each of five levels, with a 300-action
60-simulated-second horizon, wheel-drift odometry and camera pitch 82. On
every registered `(level,index)` the original unchanged parent (`parent`),
the fixed epoch-1 teacher-label model (`control`), the fixed epoch-1
parent-label model (`treatment`) and exploring teacher use the same scene,
start and seed. The unchanged parent matters because both new models received
an extra epoch and optimizer reset. Students are single-policy with
no teacher takeover, ensemble, search cue, sampling or action intervention.
Each level uses 32 distinct layouts/start poses: levels 1–3 map index `i` to
layout `290+i`; levels 4–5 map it to `291+2*i`. Variant is `i%16`; game
seed is `1800000000+100*level+i`. Some layouts and variants repeat across
levels: there are 48 distinct layout IDs across the five levels, so 160
games are not 160 independent room geometries. Those IDs and
seeds have not been established as disjoint from complete model ancestry.

`protocol.py` provides the exact prospective mapping and gates. Each student
must achieve at least 29/32 delivered games per level, at least 29/32 first
virtual pickups on L3, at least 80% of L4 opposite-side placements delivered
by the horizon, under 2% inclusive 20-action back-and-forth on each level,
and deliveries/minute at least the teacher's per level. The doorway
denominator includes censored and zero-time placements; later placements are
trajectory-dependent and correlated within each game. A conservative
non-regression checks also report matched per-seed wins/losses and require
the treatment's delivered-game count at least both the original parent's and
the extra-epoch control's. These conservative comparisons are additional to
the explicit goal thresholds. Retain and
report incomplete or failed games; never calculate a passing fraction by
dropping them. These virtual events do not establish physical grasp or release.

`metrics.py` accepts **already independently audited saved games**, not raw
untrusted directories. It requires exact 32 expected seeds, initial search
state, 300 action rows, registered arm/game/level and saved-score version,
valid event sequence and finite pose/odometry. It requires caller-supplied
registered model hashes and compares the three arms' supplied scene hashes
and initial robot/brick placement across all four arms for each seed. It reconstructs the inclusive
20-action heuristic, separately reports the 50-action odometry/travel
indicator and a 100-transition truth-pose search-return indicator. The latter
includes initial and terminal windows and stationary periods; it is not a
complete loop detector. The 100-transition accounting includes the initial
pose and thus is not identical to the older `goal-report.py` implementation,
which omits the first possible window. A current-source build is expected to
use the explicit `pose20-final-inclusive-v2` score marker; legacy comparisons
must opt into their separately pinned `legacy-v1` convention. These metrics
alone do not verify scene identity, matched initial placement, actual actor
inputs, binary/runtime execution or independent camera provenance. An outer
auditor must prove those for all four arms and all 640 games before drawing
conclusions; incomplete evidence cannot pass.

`world_geometry.py` parses PBENV001 bounds, spawn and static box colliders,
checks diverse-layout room, partition and obstacle metadata against those
colliders, and hashes exact collider geometry independently of layout title,
record names/order and start pose. It additionally records a float32 projection
of collider parameters as an overlap hint, because the simulator sends
float32 boxes to physics: slightly different f64 file values can become the
same physics shape. This improves on raw file hashes, whose headers include
the layout ID. It does not verify the rendered vertex mesh, bit-exact native
trigonometry, equivalent geometry represented as different box arrangements,
or near overlap. `ancestry.py` inventories only the 48 shard paths pinned by the
parent L35 source audit, reconstructs its archived scene/start digest and
reports current result/report hashes, case/environment hashes, collider
digests, starts and 1,024 declared seeds. That archived digest does not bind
the historical result/report bytes, and the scan is not an atomic snapshot
or a complete pretraining lineage. Prior diverse-prefix, additional selection,
teacher and new parent-collection evidence must also be inventoried, with
explicit safe resolution of catalog links. No missing lineage should be
silently treated as proof of disjointness.

Before actual selection, separately review and bind all of the following:

1. The completed full-pair receipt, exact fixed-epoch model packages and
   training schedule; a pre-registered choice of arms and selection rule.
2. A reproducibly built generator and its transitive source inputs; world
   collider and rendered-geometry consistency; explicit known ancestry,
   case/environment/seed inventories and exact plus near-geometry review.
3. A protected selection-role catalog and native ingestion boundary that
   cannot accidentally feed selection or reserved held-out data to fitting or
   validation. The existing v3 runner requires `fit:true` and cannot consume
   this role unchanged. Existing native binaries and opaque prior datasets
   can currently bypass the prototype guard.
4. A new runner that freezes both models, teacher, scene bytes, placement,
   executable, runtime and all transitive audit sources before play. Record
   and check the actual pre-inference image, post-cue feedback, hidden state,
   raw policy output and applied action at the correct boundary; the initial
   post-placement observation cannot be inferred from a saved pre-placement
   `actor-495.rgb`. Provenance should not be overstated as raw-camera or
   trusted-execution attestation.
5. Reviewed per-arm process supervision, serial GPU scheduling, fresh idle
   baseline, current disk reservation and full final inventory. The machine
   has been close to its disk limit; preserve all failures and partial evidence.

The 32-game-per-level, four-arm schedule is **640 games**. Compared with the
earlier 480-game selection, this adds 160 parent-reference games (one third
more evaluation time and artifacts, before nonlinear setup/audit costs).
Actual runtime, disk use and free-space limits must be checked live; the prior
2.5 GiB three-arm output is not a reservation for this run. A teacher rate or
one favorable selection is not promotion: compare all reliability, doorway,
back-and-forth and longer-loop results without sacrificing reliability, then
use genuinely untouched held-out rooms only after their protection and
preregistration are established.

CPU fixtures, with no candidate or held-out scene generation:

```sh
python3 -B -I experiments/fresh-selection-design-v1/test.py
python3 -B -I experiments/fresh-selection-design-v1/world-geometry-test.py
python3 -B -I experiments/fresh-selection-design-v1/ancestry-test.py
```
