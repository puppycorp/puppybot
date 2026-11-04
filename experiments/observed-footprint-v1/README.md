# Observed-floor footprint regression

Run `python3 experiments/observed-footprint-v1/test.py -v` from the repository
root. The CPU-only test copies the archived simulator and library from
`build/flex/sim/levels-v2/pitch82/dock-clearance-build-v1`, inserts the current
`ps_nav_observed_clear` function into that copied simulator, and compiles the
full copied simulator with `build/flex/control/compiler`. It also compiles
two native probes, using the archived and current functions respectively.
Temporary files are created outside the archives; no robot or renderer runs.

The probe checks all 45,000 combinations of 72 headings, 25 relative
positions, and 25 individual blocked cells. A separate Python rectangle/square
intersection calculation is the expected result. The selected inputs are
synthetic and do not measure the frequency of missed obstacles in real maps.
Further checks cover a recorded geometric counterexample, the existing fine
map fallback, map boundaries, and rejection of nonfinite poses.

The guard still accepts a coarse-clear cell without consulting its fine map,
even when fine subcells are unknown or blocked. This pre-existing evidence
policy remains a limitation; the test explicitly characterizes it and does
not establish that actual floor is clear or that physical driving is safe.
