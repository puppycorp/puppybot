# Offline candidate target visibility

The native survey checks each pre-action actor RGB frame in the admitted 172
histories against the source dataset, projects the stationary recorded target
with that frame's TCP camera metadata, and looks for at least two saturated
pixels near the projection inside a fresh recorded color component. It found
3,864 candidate frames in fitting histories and 965 in validation histories,
across 168 histories. The labels describe image coordinates, never robot inputs.

This is a heuristic. Color components, occlusion or other colored objects can
produce false candidates; a projected point by itself does not prove visibility.
Eight examples spanning fitting and validation histories were manually viewed;
that sample is not a comprehensive label audit. The survey, inputs, counts and
candidate list are preserved under `build/flex/sim/memory-pose-v1/target-visibility-v2/`.

`prepare.flex` independently recomputes candidate projections and local pixel
counts, checks candidate order, source RGB bytes, action timing, pre-consumption
phase, split and hashes, and packs only candidate image positions. The accepted
sidecar and receipt are in `build/flex/sim/memory-pose-v1/target-candidates-v1/targets/`.
Masked frames do not assert absence. Its target SHA256 is
`9846229a1a28aa77c7e8653d1bbe14dbe6185c27d90a46b77d68b5e1bf0e5294`.
