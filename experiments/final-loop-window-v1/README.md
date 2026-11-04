# Read-only final-window audit

The collector currently counts 20-action back-and-forth windows before each
command. It therefore does not check the window ending at the final post-action
pose. `audit.py` reconstructs the original counts from each saved decision log,
checks them against each game result and the aggregate report, then includes
that final window and reports the difference. Its output is a local saved-data
diagnostic: the selection monitor remains failed and this does not establish
that the heuristic catches every loop, a policy improvement, or physical behavior.

Run from the repository root:

```sh
python3 -B -I experiments/final-loop-window-v1/test.py
python3 -B -I experiments/final-loop-window-v1/audit.py
```

The full audit reads approximately 1.3 GiB of existing decisions and writes no
experiment files. It is specific to the saved five-level selection with 32
cases per arm and a 300-action horizon. See diary entry 96 for results.

The current collector source emits the version `pose20-final-inclusive-v2`.
`datasets/visual-control/chase-v1/levels/audit-heldout-inclusive.py` and
`qualify-selection-inclusive.py` provide future strict validators, but they
are not integrated into an enabled runner. The historical auditor remains
unchanged and must not be used to qualify new scores. See the diary for
compatibility, tests and remaining integration work.
