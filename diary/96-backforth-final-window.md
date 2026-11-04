# Final back-and-forth window in the saved selection (3 Nov 2026)

The existing collector checks each 20-action back-and-forth window at the
pre-action pose, before it executes the next command. For an episode ending at
300 actions, it never checks the window ending at the final **post-action**
pose. Its current saved-data checker mirrors that boundary. This can undercount
measured action time and needs correction for future selection and held-out
gates; the original historical results and monitor receipt remain untouched.

A read-only reconstruction checked every action and pose in the saved fresh
five-level selection. For each of the 480 games it reproduced the original
reported count, then included the final possible window and took the union of
flagged action indices. Across all arms and levels this added 27 actions. No
per-level/arm result changed which side of 2% it falls on for this selection:

| Level | Older student | Heading model | Teacher |
| --- | --- | --- | --- |
| L1 | 403 / 9,600 (4.1979%) | 456 / 9,600 (4.7500%) | 1,147 / 9,600 (11.9479%) |
| L2 | 505 / 9,600 (5.2604%) | 347 / 9,600 (3.6146%) | 665 / 9,600 (6.9271%) |
| L3 | 102 / 9,600 (1.0625%) | 391 / 9,600 (4.0729%) | 116 / 9,600 (1.2083%) |
| L4 | 190 / 9,600 (1.9792%) | 345 / 9,600 (3.5938%) | 1,054 / 9,600 (10.9792%) |
| L5 | 390 / 9,600 (4.0625%) | 135 / 9,600 (1.4062%) | 1,623 / 9,600 (16.9063%) |

The L4 older-student value was especially important to check because it is only
two actions below the strict threshold. It gains no flagged actions from the
final window in this saved selection. The output is still an observation on
training-family games with the original resource monitor **failed**, not a
held-out pass, execution attestation, complete loop measure, or physical
result. This 20-action truth-pose heuristic can miss other back-and-forth
patterns, and the separate longer-search-loop measure remains necessary.

The script rejects changed per-game counts or aggregate shares, malformed
poses/actions, and basic file changes during a read. It bound the locally read
report SHA-256 `9954ecf9586911675e3674ac99f5a3cd5c4c0acae8924c4486d973676634c937`
and an ordered digest of the game input hashes
`cad12e2b25b8a1862fbff878eb97e17d88837a1610ebc3dad90d21ec746659b5`.
These hashes do not repair the original failed monitor or prove execution.
Four CPU tests cover the previously missed sole window, overlapping window
unions, insufficient actions / large motion, and non-finite input.

Artifact: `experiments/final-loop-window-v1/`. No policy or simulator was run,
and no existing output was changed.

## Future collector and versioned verifier

The current collector source now evaluates the final pose after the episode's
last action. New results identify their accounting with
`backForthMetric: "pose20-final-inclusive-v2"`; `backForthSteps` has the
inclusive count. This can differ from the unmarked legacy field by up to 20
newly flagged actions per episode, so compare scores only after reconstructing
them under the same definition. The current shared compiled control binary was
not replaced; the updated source was compiled into an isolated temporary binary
and its help command succeeded. No simulator game or GPU training was run.

A CPU-native probe of the real tracking function passed an exactly 20-action
final window, overlapping windows, a moving endpoint, and consecutive episodes
with stale ring-buffer bytes. A separate inclusive held-out auditor recomputes
the full window on candidate and teacher traces and rejects missing or wrong
version markers. Its entry point requires its own source hash in the registered
input manifest. A selection helper likewise validates the version and inclusive
count before returning games. Seven focused inclusive tests, 12 existing legacy
held-out tests and 17 existing selection-qualification tests passed.

The old, SHA-pinned auditor and scripts remain unchanged so archived selection
scores and re-audits retain their original meaning; `retry.verify()` still
accepted the old frozen inputs after the source change. An old auditor can
coincidentally accept an inclusive score if its final window adds nothing, so
it must only be used for legacy results. The new verifier and selection helper
are **not integrated into a runnable qualification or held-out pipeline**:
both existing qualification and held-out runner remain deliberately disabled.
Before enabling any future runner, review and integrate the inclusive helper,
register its complete source chain before play, and ensure it invokes the new
verifier. These code and synthetic tests do not demonstrate a policy gain,
validate all loop types, or establish a physical result.
