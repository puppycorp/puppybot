# Saved coarse and fine floor observations

`audit.py` reads the 32 retained paired coarse/fine floor snapshots in
`build/flex/sim/held-map-replay-v4/map/episode-0` and their recorded scan
poses. It compiles the current `ps_nav_observed_clear` into a temporary copy
of the archived simulator, calls the native guard at each pose, and counts
intersecting fine cells using independent rectangle/cell geometry. Poses are
rounded to 1 nm in both calculations. A marked fine cell can mean unknown or
occupied; the script checks the last snapshot against its retained evidence
arrays to distinguish those two cases. Inputs are hashed before and after the
probe, and the saved report includes their hashes. This is consistency with
local files, not independent attestation of their origin or a complete build
provenance chain.

Run from the project root with NumPy and the local compiler available:

```
python3 -B -I experiments/saved-floor-resolution-v1/audit.py > /tmp/saved-floor-result.json
cmp /tmp/saved-floor-result.json experiments/saved-floor-resolution-v1/report.json
```

The saved 32 snapshots represent only two repeated robot poses in one prior
replay, not 32 independent scenes. They show a disagreement between the
existing coarse acceptance policy and a hypothetical all-fine-observed rule at
those poses. They do not show which rule would yield a successful route, prove
that a given planner call was made there, or establish physical safety.
