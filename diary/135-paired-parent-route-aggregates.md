# Paired parent-route dataset candidates (4 Nov 2026)

Two fixed dataset candidates were built from the verified 1,029-history
aggregate and the two fitting histories in [entry 132](132-parent-route-collection.md).
Each has 1,031 episodes: 935 fitting and the original 96 validation histories.
The companions remain excluded. The new first-delivery prefixes retain the
same observations, feedback, map, valid-frame state, executed actions and
weights in both arms. The control uses teacher labels and the treatment uses
the recorded parent actions; exactly 35 and 31 supervised labels differ in
the respective prefixes. Suffix frames remain valid for recurrence while
their new action-label weights are zero.

The guardian checked enough free disk for one fully unshared logical output
before each arm separately, required Btrfs reflinks without copy fallback,
and retained partial output on failure. Both reservations passed. The
independent full-byte re-audit reconstructed both outputs from frozen sources,
verified baseline and shifted validation bytes, source and receipt hashes,
the distinct single-link inodes, and the guardian and supervisor evidence.
The report remains `candidate_data_only`; this is not a trained model, a
selection result or a physical test. Device-side trainer masking and backward
behavior still require validation.

Control data SHA-256:
`b9dc5993760a0b8117d303cbdd083eca21014f8824ce52d796715c90d349ea84`.
Treatment data SHA-256:
`6d70db07119cedda63acb7ee044bbd96fc864e3609894be9cb78101b50769`.
Both map files have SHA-256
`8d970ce34bfa5acd626598ea843fe5895427814a02582dcd4bc0a9116779affb`.
The registered plan SHA-256 is
`6ffffd46eae3c9337c2f3855e0a4da36476b022b2b8438efbd7445046dfe152c`;
the completion receipt SHA-256 is
`fd8ff0ecb716b50fbc3f196aff1da313cf0e8850b447c2b3e1e7b88154cf56ab`.

Across 764 guardian samples, minimum free disk was 45,780,455,424 bytes;
sampling cannot exclude brief unobserved changes. Btrfs reported 12.31 GiB
total, 24 KiB exclusive and 2.24 GiB set-shared for the paired directory;
because extents are shared with upstream files, those figures do not directly
predict new or reclaimable space. Artifacts are under
`build/flex/sim/levels-v2/pitch82/parent-route-paired-aggregate-v1/` and its
corresponding monitored directory.
