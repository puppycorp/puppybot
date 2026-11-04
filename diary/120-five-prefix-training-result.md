# Five-prefix training: fixed epoch 1 (4 Nov 2026)

The monitored exploratory warm-start finished one epoch from the registered
parent on the verified five-prefix aggregate. The saved HIP backend marker and
training receipt identify the Flexscript/Pup HIP runtime; the curve records
467 optimizer steps. The 1,029-episode input has 933 fitting episodes and 96
validation episodes, including five teacher prefixes in the fitting split.
The final training and validation losses were 0.304445 and 0.323082; these
losses are not evidence of better task performance.

The fixed epoch-1 checkpoint is read-only in the inference package, with
SHA-256 `91aeb6803f98c9fbc00bb77fee34011fccd0388c54406708c093cc13fb15efc9`.
It was fixed in advance, not chosen by validation. The parent weights SHA-256
is `9c586f40ad6fc1a13a17f325cd3b33da5aca07e4790ee0922fd59049cd89f0d1`;
the plan SHA-256 is
`fc20b722234564e0b352f663d144817a128122e35e1cd822c3780083efed65e0`.

An independent post-exit audit recomputed the full frozen inputs, checked
the completion receipt and all linked hashes and clean subprocess statuses,
replayed the saved GPU/disk telemetry checks, verified the saved training
order and mirror mask, and compared the complete output inventory and fixed
package against the recorded evidence. The telemetry contains 299 GPU samples,
with minimum recorded free VRAM 9,702,318,080 bytes and minimum recorded free
disk 46,954,500,096 bytes. The monitored completion receipt SHA-256 is
`f0ef47da2f870e18517cf71ce9eb47be6f558f84048b7d536271e447fa7e7055`.

The result remains `training_diagnostic_only`: it is one exploratory training
seed, not a comparison against the parent and teacher, a held-out pass, or a
physical robot delivery. The training-family selection runner still needs to
be completed and independently reviewed before it can assess this checkpoint.
