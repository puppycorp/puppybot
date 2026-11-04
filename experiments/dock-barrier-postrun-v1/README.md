# Saved rendered worker-barrier postrun audit

This CPU-only analysis preserves the original trial's censored receipt. It
independently reruns the original audit, then reuses its inherited evidence
checks with a barrier trace parser that validates a constant simulated clock
offset, consecutive ticks, and map applications. It verifies the completed
trial inventory and selected receipt hashes before and after the analysis.
It does not prove the original monitor passed or attest actual execution.

```sh
python3 experiments/dock-barrier-postrun-v1/audit-test.py
python3 experiments/dock-barrier-postrun-v1/audit.py \
  build/flex/sim/levels-v2/pitch82/dock-barrier-rendered-monitored-v1
```

`report-20261103.json` is the saved result from that invocation. Two separate
invocations produced SHA-256
`85a6bee6b86bf48aceba5f1c13397eccf2204ce83e0ee63d3d78fefa03379ef0`.
The specific observations and their limitations are recorded in diary 93.
