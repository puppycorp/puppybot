# Neural exploration experiments

These experiments train a small frontier-scoring network. Its inputs are the
robot's partial map, estimated pose, scan visits, and reachable candidate costs.
It changes candidate scores only. The RGB mapper, traversability masks, native
route planner, collision guards, and physics remain unchanged. The production
explorer continues to use its existing heuristic.

`bootstrap.py` is the first idealized 2D experiment. Its synthetic validation
improved, but six short native RGB trials did not demonstrate better exploration.
The retained assessment is under
`build/flex/sim/neural-exploration-n1v_6ig8/assessment.json`.

The second experiment uses actual recorded wrist-camera mapping inputs:

1. `freeze.py --output NEW_DIRECTORY` retains a private simulator, robot asset,
   mapper, policy hook, and source manifest. The hook never receives reference
   geometry or actual poses.
2. `native_data.py --workspace DIRECTORY/workspace --inputs INPUTS.json
   --output DIRECTORY/data` replays saved stereo pairs. It checks raw RGB against
   saved PNGs and byte-matches every observed/safe map before extracting examples.
   The input JSON lists `run`, `environment`, `scene`, `split`, and optional
   sampling `stride`. Scene identities must be disjoint across train/validation.
3. `native_train.py --data DIRECTORY/data --output DIRECTORY/training` trains
   three model seeds. Minibatches balance decision states. Model/heuristic mixing
   is selected by equal-scene validation regret, then saved in `runtime.json`.
4. Freeze the checkpoint and runtime configuration before native held-out tests.
   `native.py --artifacts DIRECTORY --seeds 71001 71002 --scans 8
   --steps 70000 --repeats 2` compares heuristic, gain, and learned policies.
   Alternate repeats reverse policy order. Every trial retains RGB, trace,
   actual-motion/camera audits, offline floorplan scores, and source hashes.

Use `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1` for reproducible CPU training and
`WAYLAND_DISPLAY`/`DISPLAY` from a working graphics session for native trials.
Camera simulations need rendering even when their windows are hidden.

The second dataset has real RGB-derived **actor inputs**. Its offline labels
still approximate future 360-degree visibility within 1.3 m, divide gain by
estimated route cost, and penalize unsafe endpoints using reference geometry.
They are not executed counterfactual actions or future camera images. Reference
geometry and actual poses enter only those labels and the external evaluator.

The completed second pilot is retained under
`build/flex/sim/neural-native-data-v2/assessment.json`. It used 25,315 training
examples from four layouts, two separate validation layouts, and three model
seeds trained for 120 epochs each. The selected model was tested against both
baselines on two unseen layouts, twice per policy, with eight scans per run.

| Policy | Mean correct free-floor coverage | Mean free-space precision |
| --- | ---: | ---: |
| Existing heuristic | 4.88% | 97.21% |
| Gain baseline | 4.57% | 96.63% |
| Native-data neural model | 4.31% | 97.02% |

All twelve native trials passed their motion, camera, source, and actor-input
audits. The neural model improved the first layout but underperformed on the
second. Its improved offline validation score did not establish better native
exploration. These are partial exploration episodes, without pickup or room
completion. `reproduce.sh NEW_DIRECTORY` in that artifact directory reruns the
frozen comparison without overwriting the original measurements.

Native trials, rather than training loss, determine whether a model helps.
Report scene-level results, repeats, actual travel, map precision, protective
stops, and incomplete episodes as well as coverage. A short successful trial
does not establish room completion, six-brick collection, hardware performance,
or generalization to other layout generators.

Focused checks:

```sh
OPENBLAS_NUM_THREADS=1 python3 flex/tests/sim-exploration-learning.py
OPENBLAS_NUM_THREADS=1 python3 flex/tests/sim-exploration-native.py
OPENBLAS_NUM_THREADS=1 python3 flex/tests/sim-exploration-native.py \
    --artifacts build/flex/sim/neural-native-data-v2
```
