# Paired trainer capacity and mask prototype (4 Nov 2026)

The proposed paired aggregates need 1,031 episodes: 935 fitting and the
original 96 validation histories. An isolated trainer transform raises the
previous 1,030-episode limit to 1,031 and updates the masked auxiliary-loss
range to fitting indices 928–934, covering the five earlier teacher prefixes
and the two new proposed first-delivery prefixes. It keeps recurrent frames
after the supervised prefix while zeroing the corresponding action and
auxiliary loss seeds. It also checks the fixed split, seven prefix cutoffs
and seven-class action encoding before GPU initialization.

Four private build/FICLONE tests and six native host/sparse-shape/mask/codec
tests pass. An independent reviewer reran them and checked the boundary
indices 927, 928, 932–935 and 1030, including a batch crossing the fit-mask
boundary. The tests cover host-side synthetic loss seeds and valid-frame
recurrence; they do not establish real GPU graph/backward behavior,
prefetch concurrency, optimizer behavior or policy performance. The dataset
verifier, not the trainer, must establish the preserved baseline/validation
bytes and teacher-versus-parent label identity. The private build is at
`experiments/parent-route-paired-trainer-v1/` and has not trained a model.

After the paired-data guardian exited, a fresh private CPU build was published
and independently recompiled to the same recorded binary hashes. Its trainer
SHA-256 is `1e64ccb918d9ff53c0ccea1b8cf98d0125cdff91d80dedc276a83b9079bfcbe3`;
the build receipt SHA-256 is
`33a941d231adb3be54e41e736f192d7842c0daf0833da60f50d3aaaa07ad4bca`.
This is a reproducible CPU build, not a GPU backward or training result.
