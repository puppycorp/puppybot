# Search-only handoff trial (simulator diagnostic)

This stages a comparison on the previously used hidden-case selection scene:
archived client/simulator, isolated candidate with fallback disabled, and the
same candidate with fallback enabled. All arms use the same saved model and
scene, 90 navigation actions and at most 1,499 collector polls. Each arm has
a 300-second process watchdog; the saved-output audit has 300 seconds. The
launcher refuses existing output and its CLI is hard-disabled. A separately
reviewed outer subreaper, absolute deadline, GPU and disk monitor, and an
explicit scheduling decision are required before any rendered run. The worker
flag in the source is a caller declaration and does not establish that such a
monitor exists.

The auditor matches the whole archived-vs-disabled recorded protocol and
outcome, and every saved observation and actor input, recurrent state and action
through the enabled arm's last navigation action. The initial simulator truth
pose and object/container placement are compared only after the runs. Any
missing/failed arm, initial detector hit or zero-action arm, diverging prefix,
or run that never enters search is censored. The simulator case is selected
from earlier work and is not held-out. Asynchronous execution may cause an
otherwise valid experiment to be censored.

The opt-in client writes requests before sending them. Correlation with saved
responses establishes only local recorded intent and response consistency,
not a wire or operating-system attestation. Search command 8 and ACK 8 denote
a stopped ownership transfer to a search routine, not a target sighting,
grasp or delivery. Command 8 ACK 2 reports a fresh target and is followed by
the ordinary command 6 path; command 6 ACK 2 has a different meaning. The
search transfer's blank/no-target image is not independently recoverable from
the JSON journal, and the last pre-search actor frame does not establish that
fresh frame. Captures, release and settling are checked by a separate
post-run simulator-truth audit and must occur after collector ownership. The
simulator collector uses privileged internal simulated state. The experiment
does not prove motion causation, physical stopping, pickup, delivery or safety.

The build/source receipt and logged invocation are locally verified evidence,
not proof that the recorded binary was compiled from those inputs or that the
operating system executed them. Failure to acknowledge a stop or failure to
clean up workers censors the arm and does not establish any physical stop.
