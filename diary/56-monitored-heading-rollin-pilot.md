# Monitored four-game heading roll-in pilot

3 November 2026: the monitored collection pilot passed. The control and
treatment each collected two 300-action L5 training-layout games, with one
fitting and one validation game per arm. For fitting seed 6700000, their
starting positions and target positions matched while yaw was 0.42 and 0.35
radians respectively; their initial actor frames differed. Validation seed
6700001 used yaw 0.42 in both arms, and its complete shard data and map bytes
matched. Saved teacher/student actions differed on 252 control and 261
treatment steps across 600 steps per arm. This checks saved-label consistency,
not teacher correctness or policy improvement.

The fresh read-only audit revalidated the catalogs, start/placement checks,
all four traces and labels, the whole matching shard validation game, and all
230 recorded input hashes. In the two 34-game pilot aggregates it independently
rechecked all three validation games and their maps for equality, and all
32 unchanged slots plus maps; the remaining two slots are the student roll-ins.
The reflink treatment overlay was byte-compared in full with the native
treatment aggregate's data and map, its manifest hash matched, and the source
physical maps matched their recorded values. The original run recorded matching
source mappings before and after overlay creation. Btrfs then reported
203,743,232 bytes set-shared and 12,742,656 bytes exclusive for the overlay
data file; this small pilot is not evidence of full-scale allocation or of a
successful training run. Free space around overlay creation changed from
51,516,293,120 to 51,442,462,720 bytes, a 73,830,400-byte net difference;
filesystem free-space changes can include other activity.

The outer telemetry supervisor, heading supervisor, and control and treatment
arm supervisors exited 0 without timeout, signal or residual-worker cleanup;
their recorded wall times were 223.407 s, 193.076 s, 24.437 s and 27.948 s,
respectively. Telemetry logged 31 baseline samples across 30.000 s, 193 samples
while the heading supervisor ran, and one afterward. Baseline busy was 3% in
31/31 samples; the running samples ranged 3–20% in 193/193. Minimum nominal
free VRAM during the run was 8,884,690,944 bytes (8.275 GiB); no telemetry
errors were recorded. One-second samples miss short peaks and whole-device
activity cannot isolate Kennel service usage or responsiveness.

The four-game roll-in is a pipeline and byte-preservation test on training
layouts. It does not measure whether heading-diverse training improves the
policy, qualify held-out performance, establish physical robot behavior, or
prove authentic camera/runtime provenance. The actor's carry cue is
simulator-derived task state. The separately matched one-epoch trainer pilot
and full collection/training have not run. Evidence is retained under
`search-dagger-heading-pilot` and `heading-pilot-monitored-v1`.
