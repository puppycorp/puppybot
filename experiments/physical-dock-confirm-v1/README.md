# Simulator dock confirmation prototype

This isolated source transform explores the observed failure to confirm a home
box during discovery travel. In the saved fallback trial, dock detections at
ticks 11131, 11141, 11151 and 11161 occurred while both simulated wheel
commands were +30. Their estimated positions changed by 2.346, 3.757 and
1.043 mm; the existing 3 mm consistency gate reset the stable count from two
to one at the third detection. See `diary/68-search-fallback-independent-review.md`.

The transform defaults off and has no production build, runnable trial or GPU
entry point. When explicitly enabled in a separate simulator build, it acts
only after a fresh unconfirmed full dock detection during collector-owned
discovery travel with local non-oracle state. It commands zero drive, rereads
the same local commanded-drive fields, discards previously accumulated stability
and counts the just-captured travel frame as the first of three. This readback
is not an independent acknowledgement; only subsequent frames are sampled
after the zero-drive command. It then takes at most four
additional RGB samples on strictly increasing simulator ticks within 25 ticks.
The existing detector and its 3 mm, orientation, age and three-observation
checks remain responsible for setting home-ready. At most three confirmation
attempts are allowed per episode. Distinct frames are not a claim of statistical
independence or distinct objects.

An invalid, repeated or expired frame, detector dropout, contact, commanded or
estimated motion, camera movement, ownership change or a spent budget cancels
confirmation. Stop-command or RGB-capture failure terminates discovery with
failure. A newly confirmed floor obstacle cancels confirmation and invokes the
existing scan/replan path. A cancellation retains the existing discovery
controller; it does not invent a home location, target, safe floor or route.
If the third valid box observation and a new obstacle arrive together, the
existing collector observation order retains the learned home and the new
obstacle still forces a replan; learning the home does not mark floor as safe.
Trace metadata uses reason 1 for motion/context cancellation, 2 for expired or
spent budget, 3 for detection loss, 4 for confirmed home, 5 for stop or sensor
failure and 6 for floor-change replan. These are simulated state records, not
proof of physical stopping, pickup or safety.

Run the CPU-only tests with:

```
python3 -B -I experiments/physical-dock-confirm-v1/test.py
```

The disposable native probe executes the transformed collector and discovery
dispatch, the real dock consistency function and simulated drive state. RGB
capture, the detector's input observations, floor sensing and hardware calls
are mocked. This tests state transitions rather than a rendered scene; a
separately reviewed matched simulator experiment is needed before drawing any
behavioral conclusion.
