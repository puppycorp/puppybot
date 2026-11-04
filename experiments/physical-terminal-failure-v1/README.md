# Simulator collector terminal-failure reporting

The physical-agent simulator protocol previously used acknowledgment 5 for
both passed and failed collector terminals. The simulator now adds an optional
`collectorFailure` string when it sends acknowledgment 5 for its own failed
case stage. The field is backward-compatible with older clients, which can
ignore extra JSON fields. It is the simulator controller's report, not an
independent sensor or proof of a physical pickup, release, or braking.

The current physical-client copies a valid nonempty reason of at most 128 bytes
before the next JSON response overwrites its parser buffer. It requests and
validates the existing simulated stop before adding that reason to `result.json`.
Malformed, empty, oversized, or embedded-NUL failure detail is marked invalid;
it does not prevent the stop path. If an older peer omits the field, the result
has no new field. A terminal result remains `outcome: unverified`, and exit code
zero does not indicate a delivery. A bad or missing stop acknowledgment produces
no normal result. Stream or journal errors before the stop and result-write
errors remain uncovered by this change.

`transform.py` stages the same change in archived copies for regression tests;
the active simulator and client source now contain the changes. The tests
compile the current client, the copied full simulator and a native probe of the
simulator's actual failure-field helper. Synthetic local-socket peers exercise
failure detail, older peers, malformed and escaped messages, and a missing
stop acknowledgment. They do not run a rendered simulator or physical robot.

```
python3 -B -I experiments/physical-terminal-failure-v1/test.py
```

Local socket tests may require permission to run outside a network-restricted
sandbox. No existing simulator or model binary is replaced by the tests.
