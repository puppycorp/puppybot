# Fixed epoch-1 five-level selection replay

This prepares a fresh monitored replay of the fixed epoch-1 candidate against
the parent student and exploring teacher, on 32 matched scenes per level and
300 actions per game. The scenes and seeds were already used in the training
family: these results are **selection evidence**, not independent held-out
evaluation. The earlier failed v2 monitor and all its outputs remain intact.
No model is selected or promoted by this runner.

The original strict saved-game audit remains mandatory. The report additionally
uses `outbound-five-selection-metrics-v1` to reconstruct the inclusive final
back-and-forth window, exact first pickup, L4 doorway delivery including its
denominator and censoring, longer loops, and teacher and parent comparisons.
The catalog-aware monitor is installed again in the independently reloaded
monitor and final-inventory processes. These checks are not actor, camera, or
physical execution attestation.

Registration is CPU-only and requires the fixed training to have completed
cleanly, its full saved training audit and inventory to match, and at least
38 GiB free. It pins the evaluation source graph, prior selection, model,
scene files, and training receipts. It uses the shared experiment lock,
low CPU and idle I/O priority, and nested process deadlines. Do not modify
pinned training files during training. Failed or existing outputs are retained.

CPU fixture checks (they do not run games or verify a real GPU):

```sh
python3 -B -I experiments/outbound-five-selection-runner-v1/test.py
python3 -B -I experiments/outbound-five-selection-runner-v1/supervise-test.py
python3 -B -I experiments/outbound-five-selection-runner-v1/outer-test.py
```

After training has finished and its output has been independently reviewed,
run registration from a fresh dedicated process, under an operator-controlled
session which can observe the process and receipts:

```sh
python3 -I -c 'import importlib.util,json; s=importlib.util.spec_from_file_location("freeze", "experiments/outbound-five-selection-runner-v1/launch-freeze.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps(m.launch(),sort_keys=True))'
```

Review the plan and both successful freeze receipts before scheduling the GPU
replay. The GPU launcher requires those receipts, 38 GiB free at launch, its
own dedicated process, and the inherited monitored limits. It creates only
the new v3 outputs and leaves any failed or partial run censored for review.
Run only once the GPU and experiment lock are available:

```sh
python3 -I -c 'import importlib.util,json; s=importlib.util.spec_from_file_location("selection", "experiments/outbound-five-selection-runner-v1/runner.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(json.dumps(m.launch(),sort_keys=True))'
```

Check the completion receipt and report only after the monitor and independent
final inventory have passed. A successful selection run does not establish
performance on new rooms or real hardware.
