# Fixed-weight action sampling

The three policies share the exact c38fa6 checkpoint, CNN/GRU and input
protocol. Only decoding differs: greedy maximum, softmax temperature 0.5, or
temperature 1. The local RNG seed is 73 and resets with zero recurrent memory.
It reads no scene, target, time or task information. The original seven joint
actions remain unchanged; no scan, collision override or controller was added.

Native contracts check quantiles, legal actions, uniform sampling, invalid
values, extreme logits, temperature sharpening, reset replay and greedy ties.
Each policy passed exact forward parity over 708 frames with zero logit and
memory error. The greedy binary also replayed a previous successful episode's
132 commands exactly, including its real approach and docking acceptance.

All 24 canonical screen audits passed. Greedy scored 1/8 returns and 1/8
approaches; temperature 0.5 scored 1/8 returns and 2/8 approaches, with its return
in the hidden room; temperature 1 scored 1/8 returns and 1/8 approaches. Neither
sampling variant returned in both room types, so full-32 validation and the
predeclared additional randomness seeds were not run. No completion-rate
improvement was demonstrated and no policy was promoted.

The original job finished the tests, then exited 1 because its final relative
hash manifest was checked from the runtime directory. All original files and
failure status are retained. A separate check from the project directory
verified every frozen recipe, binary and runtime hash; `integrity-recheck.exit`
is zero. No physical episodes were rerun or scores changed. Source `run.sh`
now restores the correct directory before its final check.

Artifacts are under `build/flex/sim/stochastic-v1/`. See [results.json](results.json).
