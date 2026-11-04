# Fixed-epoch matched heading package

3 November 2026: the matched heading models have been packaged as a fixed
epoch-8 pair under `pitch82/search-dagger-heading/models/heading-epoch8-pair`.
The package manifest has schema `puppybot.fixed-epoch-pair.v1`, records epoch
8, and has SHA-256
`a8983bbb657700ad361dfb4d9c64b4b6654bf80495c5412c159cf858bb6e9322`.
The manifest and both packaged weight and receipt files are mode 0444. These
permissions and hashes are useful identity checks, not tamper-proof proof.

I independently hashed and compared the small weight files and confirmed that,
for each arm, the packaged `weights.bin`, source `epoch-8.bin`, and source
`last.bin` are byte-identical and share the hashes below. The package does not
use the source model's validation-selected `weights.bin`:

| Arm | Packaged epoch-8 and final snapshot SHA-256 | Source validation-selected weights SHA-256 |
| --- | --- | --- |
| Control | `a8c2573f11e00c8b5687d0a352b948e42679d9d5a13e662fffdb47801b4db926` | `0403290e57b172365ed62e6fe99298d097fad776d1164c3cd5c686a37e9e9bad` |
| Treatment | `cc427c7c7ae7312573d0b1a6ff48d3555207dd6bf1d82d3a1c38dca215fe967e` | `b4256b8177d8db18bfbe94733a76c9367ae925ac30c835ed26fdf903037f3bf0` |

Each packaged weight file is 1,375,680 bytes. The package's derived receipts
identify the fixed checkpoint and retain the hash of the original training
receipt; the original receipts copied into the package match the source
receipt hashes. The manifest's source curve hashes also match the small saved
curve files. The recorded receipts specify the same parent weights, training
seed 6900000, batch size two, eight epochs, mirror augmentation and a
simulator-derived carry cue. The saved matched-training report records 3,712
optimizer steps per arm. See [entry 59](59-full-heading-training.md) for the
training and monitor evidence.

This inspection did not rehash the multi-GiB datasets or independently verify
every packaged executable and kernel. Equality of the named checkpoint files
and the saved training records does not independently attest when the snapshot
was produced or what the operating system executed. It does not establish
identical intermediate random choices, an improvement over the control,
teacher parity, an independent held-out result, or physical pickup and
delivery. The fixed selection plan was being registered separately; this
package identity is not a selection result.
