# 51. Actor-input instrumentation pilot

_3 Nov 2026, one paired training-layout game_

An isolated instrumented control and the existing control each ran the same
epoch-8 policy, seed and training-layout scene for 300 actions under a
supervisor. Both processes exited cleanly, with no timeout or remaining
workers. The actor-input and parent-side argv-intent journals passed their
independent checks. Compared actions, feedback, saved images, placements and
results matched; both runs reached one target and delivered none.

The original run did not save its first post-placement actor image, so full
image parity cannot be established. The journals do not independently prove
the actual loaded runtime, model execution, camera or contact authenticity,
or command application; the argv journal records child exec intent. The
carry cue remains simulator-derived. This is one diagnostic training-scene
pair, not held-out qualification or physical-robot evidence. Its frozen
inputs, journals and audit are in
`search-dagger-l4-matched/actor-attested-pilot`.

## Experimental policy-stream witness

A separate, opt-in CPU-tested proxy now hashes each fixed-size policy request
and response as it forwards them, and an auditor joins those digests to the
existing actor-buffer journal. It stores two 32-byte digests per action plus
small JSON metadata, instead of another full copy of every 85 kB input. The
existing full actor journal is still required. The current join is limited to
one game and 512 frames; it is not integrated into the active control or
policy launcher.

Six local-socket CPU tests passed, including real stub-peer byte transport,
missing/reordered/duplicated/altered records, partial I/O, an I/O timeout,
a signal just after fork with repeated signals during cleanup, and changed
model or registration checks. The proxy reaps its direct policy child. It
requires a separate subreaper/process-group supervisor for escaped descendants
and an absolute wall-clock deadline; its own timeout is per I/O operation.

The auditor deliberately reports `stream_digests_consistent_unverified_provenance`.
Its supplied supervisor status may be from another run, and its registration
has no proof of being written before the run. Hashes do not prove the proxy or
policy executable actually loaded, the child read the socket, a GPU model
computed the response, or the camera and contact data are authentic. Neither
the stream journal nor its inputs are protected from owner fabrication. No
real policy, simulator or GPU was run for this witness test. Both selection
qualification and the held-out runner remain hard-disabled; existing results
have not acquired new attestation retroactively.
