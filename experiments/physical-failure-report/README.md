# Simulated physical-peer failure reporting prototype

This prototype builds a copied client from the preserved handoff-v3 source
archive. It changes no active client, simulator, or archived source. Run
`python3 -I experiments/physical-failure-report/prepare.py NEW_DIRECTORY` to
compile separate baseline and candidate clients and save their input hashes.
No simulator or GPU is started by the build.

The candidate's `PUPPYBOT_SIM_FAILURE_REPORT=1` opt-in records a best-effort
`failure.json` in its new output directory when the physical-protocol peer
returns a validated `ack=6` or a directly checked peer frame, status, drive
echo or stream operation fails. A validated ack 6 records
`peerReportedZeroDrive: true`, because the peer echoed a zero command; it
does not set `stopCommandAcknowledged`, which requires a separate valid stop
reply. EOF, a timeout, a bad stop reply, and malformed data do not establish
either condition. The report latches the first failure, exits nonzero, and
leaves delivery and physical stop `unverified`. It does not issue a recovery
maneuver or feed failure fields to the policy.

The report is not guaranteed: process termination, full disk, write failure,
unhandled failures inside shared helper functions, and failures in the policy
stream can occur before it is written. Missing `failure.json` is not success
or proof of a stop. The client exits directly on these failures: the prototype
does not itself guarantee child-process cleanup or command a fresh stop, and
requires an external process watchdog and an independent physical stop
mechanism before any physical integration. The existing local stream deadline defaults to 45 seconds;
this bounds an individual simulated peer transfer, not a whole task or a
physical robot's stopping time. No real motor, contact sensor or physical
pickup/delivery has been tested.

`python3 -I experiments/physical-failure-report/test.py` builds temporary
clients and runs CPU-only local Unix-socket peer fixtures. The sandbox may
need local sockets enabled. The timeout fixture deliberately waits through the
real 45-second deadline. Normal-path comparisons include actor bytes, command
and observation journals and result bytes for baseline, disabled candidate and
enabled candidate; failures cover bad responses, EOF, stop replies, latching
and an unwritable report directory. A failure after a valid stop reply also
checks that only the simulated acknowledgment is recorded. Stub peers do not
establish simulator or hardware behavior.
