# Blue context around small box markers: offline research

This isolated transform applies an experimental local colour check to the
existing opt-in three-pixel rim-marker detector. When enabled, each marker
component must have at least eight blue-like pixels within an 11×11 pixel
window, and at least two accepted components must have fewer than 100 blue-like
pixels there. This is a crude boundary proxy, not a continuous rim check; its boundary count includes all accepted markers, not only markers used by the fitted pose. The thresholds were selected after inspecting these saved images;
they are not independently calibrated. With the flag disabled the existing
four-pixel detector is unchanged. This code changes no normal simulator,
release policy, archived source or prior outputs.

Replay the copied native detector on the saved frames and synthetic controls:

```
python3 -B -I experiments/dock-marker-blue-support-v1/test.py
```

The test reuses the older receipt and checks local hashes for all 45 stereo
barrier survey images, camera metadata and the candidate trace. Those new hashes are local
consistency checks, not independent camera attestation. It compiles the
archived copied simulator detector, tests the old and new detectors, and sends
five consecutive recorded frames through one native detector state. The test
fixture's synthetic test colours show a decisive limitation: the gate rejects
magenta patches on black or on solid blue squares, but accepts the same
patches on half-blue, half-black squares even when there is no box. The threshold must not authorize release.

The five positive recorded frames use one settled simulated viewpoint, with
only two repeating image hashes; they are not five independent scenes, and
replaying them does not prove physical camera freshness. These are post-hoc
selection diagnostics. No robot or rendered simulator was run and no change
in pickup or delivery has been demonstrated. See diary entry 98.
