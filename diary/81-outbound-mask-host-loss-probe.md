# Outbound mask: native trainer host-loss probe (3 Nov 2026)

The derived outbound-prefix data in entry 79 keeps valid recurrent frames
after their action labels are masked. A CPU probe now exercises the native
trainer's `PVDATA04` row validation, batch fill and host loss loops with such
an unsupervised suffix. It uses a disposable source copy and removes device
execution, transfers and optimizer work from the probed loss function. This
does not execute the model or prove parameter gradients on the GPU.

The probe checked that valid suffix images and feedback remain in the batch.
With default phase masking, the suffix produced zero direct continuous and
categorical action, phase and event output seeds. Reversal and phase-consistency
checks use contrasting logits and positive controls: the respective penalties
change supervised-prefix seeds when enabled, while the masked boundary adds no
suffix seeds. Independent review checked the actual retained trainer loops and
repeated the CPU test after those positive controls were added.

The same probe deliberately enables `--phase-from-valid` and valid pose, map
or target auxiliary labels. Each can seed a suffix whose action mask is zero.
Consequently future training must pin loss options and auxiliary masks, rather
than assume action-label masking suppresses every objective. The recurrent
model's time-causal structure is consistent with zero suffix output seeds not
adding a suffix loss, but the GPU backward graph and optimizer have not been
measured. No candidate model was trained in this check.

Run `python3 -B -I experiments/outbound-mask-host-loss-v1/test.py` for the
native CPU probe. Artifact: `experiments/outbound-mask-host-loss-v1/`.
