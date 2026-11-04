# Fitted-corner connected-blue cue: offline research

This diagnostic runs a copied native detector from the earlier three-pixel,
blue-context experiment for **one frame at a time**. An instrumented copy of
its probe exposes observed-marker indices associated with estimated corners in
`ps_dock_corners` and their pixel centres. The Python postprocessor labels four-connected blue-like pixels and
requires a region of at least 200 pixels to occur within the 11×11 square
around at least two distinct corner-associated markers. The original detector and runtime
are unchanged. The threshold, neighbourhood and connected-region selection
were chosen after inspecting the saved images.

Run:

```
python3 -B -I experiments/dock-rim-connectivity-v1/test.py
python3 -B -I experiments/dock-rim-connectivity-v1/audit.py > /tmp/rim-connected.json
cmp /tmp/rim-connected.json experiments/dock-rim-connectivity-v1/report.json
```

The audit checks the locally recorded image and calibration hashes in the
prior receipt, runs the actual copied fit, and compares the cue on 45 saved
barrier survey frames, three older positive views and three synthetic images.
Some source and file hashes and the OpenCV/NumPy versions are saved in the
report. These are local consistency checks, not a fully pinned build or an
independent attestation of camera images, robot execution or held-out data.

The cue rejects the separated half-blue patch spoof that passed the prior
colour-context experiment, but an artificial image of blue lines connecting
the markers also passes. It has not been evaluated on a representative range
of box-free scenes, lighting, occlusion, moving views, actual physical images,
or tracking after the first frame. Two valid observed corners are not a
fully observed rectangle. This is evidence about a specific added visual cue,
not an identification or physical release criterion; a blue object, a blue
wall or a fabricated pattern could also satisfy it. The Python algorithm is
not integrated into the simulator or robot, and no actuator was commanded.
See diary 101.
