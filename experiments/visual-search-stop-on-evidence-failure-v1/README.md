# Stop after a visual-trigger evidence failure

This isolated simulator-only source transform extends the experimental hybrid
visual-search client. It does not modify the earlier transform or any saved
experiment. If exclusive creation, writing, or closing of `visual-trigger.rgb`
fails after the image-stall detector triggers, the client preserves any
existing or partial file, does not transfer to search, and follows its normal
simulated stop path. After a valid stop response it reports
`visualRecoveryOutcome: trigger_evidence_unavailable`, with the episode
outcome still `unverified`.

In this one failure path, the client skips the pre-send search-request intent
journal for command 3: a failed journal write must not prevent the stop
request. The ordinary protocol still validates and journals the response, and
the earlier saved-protocol auditor deliberately rejects this incomplete
record. A missing result or journal row is not evidence of a successful stop.
If the response journal, stop exchange, child shutdown, input recheck, or result
write fails, the client can exit without a result even after requesting a stop.

A blocked evidence write can still delay the request indefinitely, and failures
before this narrow trigger-file branch, process death, and unresponsive peers
are not covered. A simulated stop acknowledgment is not physical braking,
verified recovery, a delivery, or a hardware safety mechanism. No real robot or
rendered simulator was tested by this change.

Run the copied-client tests with local Unix sockets available:

```
python3 -B -I experiments/visual-search-stop-on-evidence-failure-v1/test.py
```

The synthetic peer tests include an existing trigger file, an injected partial
write, an unavailable intent journal and a missing stop response. They retain
normal, disabled, target-handoff and prior protocol checks. The fault injections
exercise specific failures rather than proving all disk or process failure modes.
