# CPU probe of outbound-mask trainer host logic

This probe copies the current Flexscript source to a temporary directory and
compiles a disposable host executable. It uses the actual `pt_check_rows`,
`pt_batch_fill` and host loss calculations from `train.flex`. Its temporary
copy removes device graph execution, asynchronous transfers and optimizer
launch from the loss function; the loss loops and mask operations are kept.
No original source, dataset or checkpoint is modified, and no GPU is used.

The fixture has four valid PVDATA04 rows: two supervised followed by two
valid but unsupervised. It checks retained image bytes, actual row validation
and batch fill, then checks that direct continuous and categorical actor,
default phase and event output seeds are zero on the unsupervised suffix.
It also uses positive controls to verify that reversal and phase-consistency
penalties change supervised prefix seeds, then checks that their seeds do not
cross the masked boundary. With predictions held fixed,
changing suffix targets leaves the direct loss and prefix seeds unchanged.
The probe confirms that `--phase-from-valid` and independently valid pose,
map and target auxiliaries can seed the valid suffix even with zero action
supervision.

This does **not** execute a real training graph, CNN, GPU GRU backward kernel,
optimizer, dataset loader on a complete aggregate, or a physical robot. The
fact that output loss seeds are zero is not by itself a numerical test of
GPU parameter gradients. The source builds the non-fused GRU forward in time
and its fused reverse scan from the last step backward; this supports a causal
interpretation, but exact GPU execution and cross-sample effects must be
verified separately. Other auxiliary heads may train suffix frames under
their own masks and require separate checks.

Run:

```
python3 -B -I experiments/outbound-mask-host-loss-v1/test.py
```
