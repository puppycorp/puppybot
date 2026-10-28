# Complete-history reflection experiment

The matched20-epoch runs are complete. Fixed10/20 native screens produced:

| Continuation | Epoch10 | Epoch20 | Hidden-layout returns |
| --- | --- | --- | --- |
| Ordinary | 0/8 | 0/8 | 0/4 at both checkpoints |
| Mirrored histories | 1/8 | 1/8 | 0/4 at both checkpoints |

All32 screen recordings passed native audit and all four exported checkpoints
matched trainer logits and memory exactly. Initial weights and final episode
order were identical between arms. No candidate passed the two-room-type
screen gate, so full32 validation and reserved final tests were not run.
This does not establish improvement over the starting model; the retained
policy remains unchanged. See [results.json](results.json).

The recovery-corpus models completed3/32 validation trips, all in the open
layout. The hidden layout repeatedly drove into the collection box. At action1,
71/72 fitting histories ask for straight driving and one asks for a left turn;
eight of24 validation histories ask for a right turn. The exact-history
diagnostic is retained under `build/flex/sim/approach35-v2/`.

This experiment compares ordinary continued training with fitting-only
horizontal reflection of complete RGB/feedback histories. A single random bit
per active history controls every frame. Steering labels, previous steering
and steering-servo feedback reverse sign; left/right wheel feedback swap.
Speed, contact and phase retain their meaning. Validation uses original views.
Image reflection also reflects asymmetric robot parts, so its benefit remains
an empirical question for native autonomous tests.

Both arms start from the exact same `a90445e2...` direct-action epoch80 weights
and accepted96-history corpus (72 fitting /24 validation). They use20 further
epochs, batch2, learning rate0.0001 and seed107. The mirror RNG is independent
of episode shuffling. Fixed10/20 snapshots receive exact native forward checks
and the same eight-scene screen. If a screen returns in both room types, both
arms at that epoch receive the full32-scene validation test. Audit rejections
are retained and count as failed episodes. The full objective still requires
at least24/32 returns and8/16 in each layout, followed by the reserved final16
and paired retained-baseline comparison before promotion.

The deployment interface remains actual TCP RGB84x84, own feedback7 and
recurrent128; the event input is zero. Training and inference use native
Flexscript/Pup CUDA.

The native contracts in `flex/scripts/test-sequence-mirror.sh` check pixel
scatter independently, command symmetry, padding, burn-in, inactive batch
items, deterministic random masks and training-only CLI handling. Actual
augmented optimizer gradients/weights match an explicitly mirrored dataset
exactly. Separate local checks found default gradients/weights identical to
the frozen previous trainer, finite-difference gradients valid, and exported
actor logits/recurrent state exactly equal to native training inference.

```sh
# Requires the accepted recovery corpus, initial policy and completed contracts.
# Every output directory must be new.
bash datasets/visual-control/sequence-mirror-v1/run.sh
```

The current experiment was launched with the equivalent separate train and
evaluation scripts. Its frozen runtime, source snapshot, recipes and receipts
are under `build/flex/sim/sequence-mirror-v1/models/`. Training/evaluation logs
are in the parent directory. `selection.json` records development qualification;
it does not claim that the reserved final tests have run.
