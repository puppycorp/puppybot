# Copied trainer capacity probe for 1,029 histories

The current PVDATA04 baseline has 1,024 episodes (928 fitting, 96 validation),
so adding the five selected teacher episodes without removing a baseline case
requires 1,029 episodes and 933 fitting histories. The current native trainer
limits PVDATA04 to 1,024, and its 8 GiB mapped-data limit is a separate check.
The proposed 1,029-by-300 data file is 6,551,848,832 bytes, below that limit.

`transform.py` raises only the PVDATA04 episode limit to 1,030 in a copied
`dataset.flex`; other data formats keep their 256-episode limit. It does not
modify or build the active trainer. `test.py` compiles a copied trainer whose
entrypoint exits after the real mapped-header and size checks, before any GPU
initialization. Sparse synthetic header files exercise 1,024, 1,029, 1,030,
1,031, and a legacy format. No real aggregate is created.

`order-test.py` compiles another copied trainer with a probe that executes the
real host row validation, coverage-map loader, the trainer's fitting shuffle,
and `pt_batch_fill` across 933 fitting and 96 validation histories. These are
synthetic one-step records, batch size two, and run entirely on CPU. It checks
that the five inserted indices are fitting, the original validation indices
stay outside the fitting permutation, the last validation episode and map can
be read, and the incomplete fitting batch is masked. It does not execute the
real 300-step GPU graph, prefetch concurrency, backward kernel or optimizer;
a raised cap is not yet validated for training.

```
python3 -B -I experiments/outbound-episode-cap-v1/test.py
python3 -B -I experiments/outbound-episode-cap-v1/order-test.py
```
