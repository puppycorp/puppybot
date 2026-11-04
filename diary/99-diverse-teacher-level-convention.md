# Diverse teacher games and the changed level convention (3 Nov 2026)

The older diverse-room results need to be interpreted using the level names
in effect when they ran. On 31 October, level 4 meant other-room placement and
level 5 was the doorway drill; the definitions were swapped on 2 November.
Entry 28's 1.78 deliveries/minute for `div-L5` therefore describes the old
doorway drill, not the current other-room level 5.

A read-only check matched the environment saved in every game to the
corresponding retained catalog, then compared the recorded initial robot and
brick positions with the partition in that catalog's layout metadata:

| Saved collection | Initial brick across partition | Games with a delivery | Total deliveries |
| --- | ---: | ---: | ---: |
| 31 Oct `div-L4` | 64/64 | 26/64 | 33 |
| 31 Oct `div-L5` | 32/64 | 51/64 | 114 |
| 2 Nov `kturn-L4` | 128/256 | 224/256 | 557 |
| 2 Nov `kturn-L5` | 128/128 | 74/128 | 89 |

Every game in these saved collections has a 300-action horizon. The older
results have no `levelPlacement` marker; the newer collections explicitly mark
`doorway drill` or `other room`. These collections use different geometries,
teachers and settings. The old diverse teacher was a sweeping teacher with
3% action noise and door-passing/early options; the current kturn teacher was
exploring. The table is not a matched comparison or an estimate for the planned
pilot. Saved files, current catalog links and hashes do not independently
attest execution, teacher quality, complete ancestry or physical performance.

## An exploratory, disjoint-from-current-selection pilot catalog

For a possible matched student/teacher feasibility pilot, use the exact
proposed mapping below, with a 300-action horizon and both arms on the same
scene and seed. Paths are relative to
`build/flex/sim/levels-v1/diverse-scenes/`. This is a *proposal*, not a frozen
registration, collection, or authorization to train. It replaces the old draft
mapping for this proposal only; the old draft and its files remain unchanged.

| Split | Seeds in order | Scene paths in the same order |
| --- | --- | --- |
| Fitting | 6910000–6910002 | `27/8`, `27/9`, `27/10` |
| Fitting | 6910003–6910005 | `29/8`, `29/9`, `29/10` |
| Fitting | 6910006–6910008 | `31/8`, `31/9`, `31/10` |
| Pilot validation | 6910009–6910011 | `33/11`, `35/11`, `37/11` |

The 12 cases have 12 different case hashes and six different environment
hashes. No proposed case or environment hash matches the frozen 160-case
five-level selection. That selection's original output monitor failed; the
comparison here uses its saved input design, not a successful monitor receipt.
The three variants within each fitting layout share one
geometry and spawn, so they are correlated. All six geometries were already
used in older diverse teacher collections, and model ancestry is incomplete;
this pilot is not unseen-layout model evaluation. Across the 24 old
other-room teacher games on these six layouts only 10 delivered, so useful
teacher labels are not assured; those old games are not a prediction for the
new paired cases. This proposal is post-hoc and does not create an independent
selection or held-out set. Keep the existing held-out range reserved.

The 12 seeds pass the prior pilot's read-only seed checks, including fixed
selection/held-out formulas and a fresh scan of 3,935 named historical records
(history digest `87bf6a105c9f8f1ea444ddbacc87df4e685c066b1ade052789f24ea635d56466`).
That scan skipped 2,254 symlinked directories and cannot discover all
unrecorded history or prove model ancestry. The proposed rows validate regular
case files, exact parent links for layout/environment, binary environment
structure, finite spawn and vertical partition; hashes are emitted by the
script. Case-file equality does not establish semantic novelty.

Run `python3 -B -I experiments/diverse-teacher-level-swap-v1/audit.py` to
reconstruct the counts, seed checks, and proposed catalog with hashes. It reads
existing files and writes no output. Before any pilot, independently review the
new design and appropriate current simulator/teacher identity, create a fresh
catalog and preregister arm commands and source chain, and use the existing
disk/GPU supervision with a complete-game audit. Separately review any
training labels and establish fresh selection boundaries. No pilot, training,
held-out evaluation or physical-robot test was run here.
