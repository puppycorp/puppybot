# PuppyBot RobotDreams

This directory owns PuppyBot-specific RobotDreams project manifests.

`puppybot-physics-prototype.json` is a PGE-generated lower-body collision
candidate, transformed through the URDF root-to-lowerbody fixed joint and
reviewed for the dynamic-vehicle fixture. Mass, centre of mass, wheel geometry,
motor values, and tyre friction remain prototype parameters—not measured
hardware authority—and must be replaced by a revisioned measurement profile
before using results for hardware prediction.

`project.json` is the canonical bin-and-ball scene for the PuppyBot model in
`../models/puppybot`. RobotDreams provides the loader, renderer, simulation
runtime, and shared example assets; PuppyBot owns this robot-specific wiring.

Open it in the RobotDreams daemon/workbench from the RobotDreams checkout with:

```bash
cargo run -p robotdreams -- open ../PuppyBot/robotdreams/project.json
```
