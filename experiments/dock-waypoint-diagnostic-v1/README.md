# Native saved-map short-waypoint diagnostic

Run `python3 -B -I experiments/dock-waypoint-diagnostic-v1/audit.py` and compare
its JSON output to `report.json`. This compiles a copied simulator with the
experimental short-waypoint function and loads the retained floor maps and
terminal pose from the candidate arm in diary 108. The inputs and simulator
compiler are hashed and checked again after the probe.

The native planner is exercised both without contact history and with two
failed-command records reconstructed from adjacent trace poses and the
preceding reported drive commands. The trace does not independently establish
the exact in-memory insertion instant or a complete historical state. No
simulated route is driven, and no hardware or robot safety claim follows.
