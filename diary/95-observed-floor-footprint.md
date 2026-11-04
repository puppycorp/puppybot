# Observed-floor footprint: missed coarse cells (3 Nov 2026)

The discovery navigation guard could accept a pose even when an occupied or
unknown coarse map cell intersects the robot footprint. Its previous fast
path sampled a 5×5 grid of points inside the 30×24 cm rectangle; an
intersection near a cell corner could fall between samples. A native probe
using the archived guard confirmed this for centre `(0.015, 0.085)` m,
heading 5°, and a blocked cell covering `[-0.1, 0] × [0.2, 0.3]` m: the
guard reported clear both before and after that cell was blocked.

`flex/sim/navigation.flex` now checks each 10 cm cell in the footprint's
axis-aligned bounds, and tests each blocked cell against the oriented
rectangle. Only an intersecting blocked cell invokes the existing 2 cm
detail-map fallback. A small geometric tolerance conservatively includes
contact at cell edges. The guard now rejects nonfinite coordinates and
heading before geometry or integer conversion. This change does not modify
archived simulator sources, saved maps or prior trial results.

The CPU-only native regression in `experiments/observed-footprint-v1/`
compiled the archived and changed functions and compared 45,000 combinations
of synthetic map cells, positions and headings over a complete turn against
an independent rectangle/square geometry calculation. The old guard
returned clear on 2,304 intersections; the revised guard matched all 45,000
cases. The selected 45,000 cases are not independent scenes or an estimate
of real-world obstacle frequency. The tests also exercised fine-map fallback,
out-of-bounds and nonfinite inputs. A full copied archived simulator with
the current guard inserted compiled successfully. No rendered episode,
held-out evaluation or physical run has tested this change.

Independent review found a separate inherited limitation: a coarse cell
marked clear is accepted without checking its 2 cm subcells, even if those
subcells are unknown. The mapper records coarse and fine floor evidence at
different thresholds, and coarse-free does not establish that all fine
subcells have been observed. The regression records this behavior; the
patch does not claim complete observed-floor coverage or physical collision
safety. A stricter fine-map policy needs its own measured evaluation because
it can also prevent the robot from finding routes.
