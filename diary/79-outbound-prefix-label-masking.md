# Outbound-only teacher label preparation (3 Nov 2026)

The experiment in entry 77 suggested using teacher outbound demonstrations
without copying the teacher's later return loops. A new CPU tool prepares a
separate `PVDATA04` aggregate that retains existing action labels through the
first virtual-consumption action and masks later teacher labels. It excludes
teacher games with no consumption within the 300-action horizon, preserves
all other explicitly supplied shards, and requires at least one fitting
teacher game with a remaining label. This is data preparation only: it has not
trained a model or established improved robot behavior.

The distinction between the dataset fields matters. In a raw `PVDATA01`
shard, offset 40 is both the label and valid-frame marker; clearing it would
incorrectly mark real frames as absent. The native `map-aggregate` instead
emits `PVDATA04`, where offset 40 is the action-supervision mask and offset 44
is the independent valid-frame mask. The tool changes only offset 40 in a new
output, keeping the full image and feedback history and preserving any mask
already zero. First consumption is taken from the saved **post-action** state,
so the action that caused consumption remains supervised. Any provided
coverage map is filtered in the same episode order.

The tool validates ordered aggregate image and row bytes against the source
shards, teacher source declarations and hashes, saved decision/action and
virtual task transitions, and optional per-shard map hashes and bytes. It
then independently reads back the derived data and map before publishing a
receipt. During review, deliberately shuffled map episodes were found to be
otherwise indistinguishable from a correctly aligned aggregate; the tool now
rejects them. It also rejects detached episode directories, outputs inside an
input tree including symlink redirects, and an output with no fitting teacher
labels. It checks free disk around each episode write and before receipt
publication, preserving partial output without a success receipt if the floor
is crossed. These checks cannot exclude races from another process changing
paths or consuming disk between observations or within an episode write.

Twelve CPU fixture tests passed, including a 300-action native-format
cutoff, shuffled maps, detached paths, simulated disk depletion and output
readback. A separate disposable `/tmp` check used the existing native
`map-aggregate` on the archived two-game teacher and two-game student pilot
shards. It retained the teacher's first 259 actions, excluded its no-pickup
game, and preserved the student games and aligned maps: three games remained,
two fitting and one validation. The archived pilot failed its expansion gate;
this check verified format handling only and none of those selection or pilot
games was used to train a model. The source shards remained unchanged and the
temporary data was removed.

Source inspection shows the current trainer reads the PVDATA04 valid-frame
and action masks separately and accepts an unsupervised suffix; default phase
loss also uses the supervision mask. `--phase-from-valid` and enabled map,
pose or target auxiliary losses can still train on valid masked suffix frames,
and `pack-data` has different supervision-order restrictions. No actual
trainer, GPU loss or gradient test was performed. Future use requires new
fitting data, explicit teacher-quality and training/validation checks,
auxiliary-loss configuration, and separate selection and held-out boundaries.

Artifact: `experiments/outbound-prefix-mask-v1/`.
