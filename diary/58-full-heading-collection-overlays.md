# Full heading collection and paired overlays

3 November 2026: the monitored full roll-in collection and CPU overlay
preparation completed. The collection report and monitored completion both
say `passed`; the outer collection supervisor and all eight shard supervisors
record exit 0, no timeout or signal, and no residual-worker cleanup. The
collection supervisor recorded 3,320.129 s. The overlay supervisor recorded
exit 0 under its 7,200-second limit, with no timeout, signal or residual-worker
cleanup, in 343.733 s. Its wrapper also recorded exit 0.

Each arm collected four 32-game L5 shards: 128 games per arm, of which 120
were fitting and eight validation games. All 40 treatment fitting starts at
yaw 0.35 and all 40 at yaw 0.49 had different initial actor frames from their
paired control starts. The reports record 19,099 control and 19,751 treatment
teacher/student disagreement steps across 38,400 recorded actions per arm;
these are saved-label checks, not teacher correctness or policy improvement.
The shard pairing evidence lists 48 byte-matched shared-heading games: 40
fitting and all eight validation games.

`pair-ready.json` reports `paired_inputs_only`: each 1,024-game aggregate has
928 fitting and 96 validation games; 896 slots are unchanged and 128 are
replaced, at fitting slots 808–927 and validation slots 1016–1023. The full
96-game validation suffix, including data and maps, passed the recorded paired
byte comparison. Both saved resource reports equal their copies embedded in
pair-ready; their source physical maps match before/after each arm and across
arms. This inspection reads the recorded evidence and does not rehash the
multi-GiB datasets; the preparation's own saved report records those audits.

For each new data file, Btrfs reported 6,520,016,896 allocated bytes in its
extent accounting: 815,009,792 exclusive and 5,705,007,104 set-shared
(87.5% of that reported total). These are point-in-time sharing figures, not
an independent measurement of net space saved or proof of future allocation.
Recorded free space fell by 274,145,280 bytes during the control measurement
and by 285,970,432 bytes during the treatment measurement; other filesystem
activity can affect both differences. Pair-ready recorded 50,058,637,312 free
bytes (46.621 GiB) immediately before publication. Each data file's apparent
size is 6,520,012,832 bytes; each map file's apparent size is 44,236,832 bytes.

Collection telemetry contains 31 baseline samples over 30.000 s, 3,286
collection samples and one afterward, with no recorded errors. Baseline busy
was 3% in 31/31 samples; collection samples ranged 3–19% in 3,286/3,286.
Minimum nominal free VRAM during collection was 8,192,655,360 bytes
(7.630 GiB). One-second device-wide samples can miss spikes and do not measure
Kennel service responsiveness or independently attest execution.

These are matched training-layout inputs and saved consistency evidence. The
actor's carry cue is derived from simulator task state, not a physical sensor.
They do not establish improved policy behavior, held-out performance, real
pickup/delivery, physical robot readiness, or full-training determinism. The
collection, overlays and partials remain under `search-dagger-heading`;
monitor evidence is in `heading-full-collection-monitored-v1` and
`heading-overlays-cpu-monitor-v1`.
