# Saved floor-map resolution comparison (3 Nov 2026)

The current native floor guard accepts the recorded robot pose in all 32 saved
coarse/fine map pairs from one older `held-map-replay-v4` replay. An independent
rectangle/cell calculation found that each accepted footprint also overlaps
fine-map cells marked unknown or occupied. The 32 snapshots contain only two
repeated poses: the first pose has 16 marked cells of 208 intersecting fine
cells; the second has 3 of 218. All overlapping coarse cells were marked free.
The script calls the compiled current guard, rather than inferring its result
from the coarse data alone.

For the final saved snapshot, the stored `evidence.npz` reproduces the fine-map
bytes. Its three marked footprint cells have fewer than three floor votes and
no confirmed occupied height evidence. Thus those three are unknown according
to this mapper, not confirmed obstacles. The combined saved fine bytes alone
cannot distinguish unknown from occupied in earlier snapshots. Snapshots,
input poses, current guard, compiler and selected archive files are hashed;
they remain local recorded evidence, not independently attested sensor data or
a complete simulator build chain.

A rule requiring every intersecting 2 cm cell to be observed would reject both
recorded poses under these snapshots, even though the coarse guard accepts
them. This does not prove that the planner evaluated either exact pose or that
such a rule would prevent an episode from moving: that requires a matched
planner or rendered test. It explains why replacing the coarse policy with a
blanket fine-map rule, without testing mapper coverage, could restrict
navigation. Neither the current acceptance nor the proposed stricter rule
proves obstacle-free physical floor.

`experiments/saved-floor-resolution-v1/audit.py` and its saved report reproduce
the result; two consecutive CPU runs produced identical report bytes. The
original saved maps were not changed. No GPU, robot or new simulator episode
was run.
