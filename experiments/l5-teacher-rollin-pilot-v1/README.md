# Tiny L5 teacher-driven versus student-driven roll-in pilot

This disabled diagnostic compares the existing exploring teacher driving the
robot against the same teacher labelling a fixed epoch-8 heading-treatment
student's actions. It uses the two **previously used training-pilot** games in
`heading-rollin-pilot-catalogs/control-L5/catalogs/shard-0`: layout 15,
variants 0 and 1, seeds 6700000 and 6700001, yaw 0.42. These games are not
fresh selection or held-out data. Their outputs are diagnostic only and must
not be inserted into a training aggregate. The teacher uses a map and known
wall geometry in data collection, but no target coordinates according to the
collector's recorded declarations; these declarations are not independent
runtime attestation. The actor is not given a teacher or map at evaluation.

The two `collect` commands use one catalog, fixed case, scene, seed, horizon,
wheel odometry, camera pitch, fetch setup and exploring teacher. Only the
student command supplies the packaged policy. Before and after each arm the
wrapper verifies the fixed-epoch package and frozen input hashes; it validates
both 2-game shard headers, data/map checksums, result and trace records, saved
scene files, actual initial pose and target, and exact initial journal bytes.
The two saved `initial.json` state files must also match byte-for-byte. This is
a conservative check and may censor otherwise usable pairs if unrelated state
serialization differs.
The PBENV001 spawn header must specify (-0.04, -0.04, 0.42), and each recorded
start must agree within 1e-6. The initial snapshot is taken before the target
placement; the logged start brick is instead checked against the first saved
post-placement action state within 1e-5.
`layout.json` is pinned catalog metadata; saved game snapshots contain the
case and environment bytes, not a separate runtime layout snapshot. Label
rows must be finite and unmasked. Teacher-driven labels must match recorded
teacher actions; student-driven label disagreement counts must match the
saved report. These checks do not prove the label's quality or which binary
executed. Missing artifacts, a failed process or a mismatch is censored and
partial files are retained.

The report gives the first virtual consumption action per matched game,
including missing/late events, and whether the teacher was earlier. A teacher
miss is right-censored at 300 actions: if the student succeeds within the
horizon it is not earlier within that horizon; if both miss their ordering is
unknown. The aggregate is unknown unless it observes an earlier teacher or
both comparisons decisively show it was not earlier. Two games are a feasibility check,
not a reliable performance comparison. Do not expand a teacher-based
training experiment unless a clean, independently reviewed pilot demonstrates
useful teacher route timing and valid labels; improvement in one pair does not
itself establish a training gain. Virtual consumption is not physical grasp.

The wrapper holds the common pitch82 lock, has separate per-arm supervised
600-second bounds and never overwrites an existing output. A separately staged
`monitor.py` uses a 2,100-second outer subreaper deadline, a 1,950-second
pilot-worker deadline, and a 30-second GPU baseline. It requires 36 GiB disk
before and after baseline, aborts below 34 GiB disk or 2 GiB free VRAM during
collection, and checks 32 GiB before publishing completion. It also bounds
input hashing and independent saved-data re-audits inside the outer deadline.
After that phase, a separately supervised 300-second final inventory check
rehashes the saved pilot tree and frozen inputs before completion; it retains
and censors evidence on a timeout or mismatch.
Completion requires complete GPU/disk observations no more than 2.5 seconds
apart, clean per-arm supervisors and exact saved report/input bindings. These
sampled observations cannot rule out transient interference between samples.

Both CLIs remain disabled pending scheduling. The pilot's eight CPU fixture
groups and the monitor's seven CPU groups passed independent review. No GPU run
or real pilot output has been created; rendered compatibility and actor
execution authenticity remain untested.
