# Five teacher-prefix aggregate: verified candidate data (4 Nov 2026)

The screened dataset candidate was built in a new directory with all 1,024
baseline histories preserved, plus five teacher-driven fitting histories.
Its header records 1,029 total histories, 933 fitting, 96 validation and
300 frames per history. The selected pilot episodes 3, 4, 5, 6 and 8 occupy
positions 928–932; their first virtual consumption actions were respectively
162, 107, 171, 43 and 38. Action supervision remains through each consumption
action and is masked afterward. RGB, feedback, valid frames and aligned map
histories remain available through the entire 300-frame episode.

The existing 928 fitting histories and 96 validation histories were retained
byte-for-byte, including maps, with the original validation records shifted
behind the five inserted fitting records. No pilot-validation episode was
inserted. An independently rerun full byte/order verifier checked every
preserved history and map, every new image and map, and all new row bytes and
masks against the source. It also verified all 78 recorded source-file hashes,
53 launch source/tool pins, the five expected seed/cutoff identities, and
before/after hashes of the four dataset inputs. These are local consistency
checks; they do not attest actor execution, camera provenance or teacher
correctness.

The dedicated low-priority supervisor held the advisory experiment lock; its
worker and final verification completed cleanly. The candidate report has
SHA-256 `34ab67f49c77f589ae6936191dd33ba85231aecc5f17aa037448fc2c4d0778b6`.
The data and map hashes are respectively
`765f160e1e07fbc2b9598f57b0f6ea14e2a4782c7b4bf383c20c9ea16b10b272` and
`fc8d693afb2acafc1e3b9e86d30a81c1f43099af21fbdb2f5b3d839148ed4896`.
Btrfs reported 6.10 GiB data and 42.39 MiB map logical use, with 613.30 MiB
and 4.17 MiB exclusive respectively; the balance shares extents with the
baseline. Root had about 44 GiB free after creation. The clone's separate inode
and the verified unchanged baseline hashes distinguish sharing extents from a
hard link. Other disk users can still race sampled free-space checks.

Artifact: `build/flex/sim/levels-v2/pitch82/outbound-five-aggregate-v1/`;
`outbound-five-aggregate-cpu-monitor-v1/result.json` is the supervisor receipt.
The report remains `candidate_data_only` and `trainingAuthorized:false`.
No training or new model resulted from data creation, and matched selection and
held-out requirements remain unproven.
