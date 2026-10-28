# Complete development-set transfer check

These layouts 6/7 scores are not an independent generalization test: 21 of
the 32 cases also occur in demonstration validation histories used for
checkpoint selection. See `../expanded-rooms-v1/README.md` for the overlap audit.

The expanded model's first hidden-room return justified measuring all 32
development scenes despite losing its open-room screen return. This widens the
diagnostic beyond the initial screen plan; the qualification thresholds and
reserved-final gates are unchanged. Eight already audited canonical screen
episodes per policy were reused, followed by the remaining 24 original scenes,
seeds and policy binaries with the original strict runtime.

All 64 native audits passed. The previous 142-history policy completed 3/32
returns and reached 6/32 bricks: 3/16 open returns and 0/16 hidden returns.
The expanded 172-history epoch-20 policy completed 2/32 returns and reached
9/32 bricks: 1/16 open return and 1/16 hidden return. It finds more bricks but
finishes fewer episodes overall. Neither qualifies for promotion; reserved
final rooms remain untouched and the retained policy is unchanged.

Artifacts are under `build/flex/sim/transfer-v1/`. See [results.json](results.json).
