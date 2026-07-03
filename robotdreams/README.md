# PuppyBot RobotDreams

This directory owns PuppyBot-specific RobotDreams project manifests.

`project.json` is the canonical bin-and-ball scene for the PuppyBot model in
`../models/puppybot`. RobotDreams provides the loader, renderer, simulation
runtime, and shared example assets; PuppyBot owns this robot-specific wiring.

Open it in the RobotDreams daemon/workbench from the RobotDreams checkout with:

```bash
cargo run -p robotdreams -- open ../PuppyBot/robotdreams/project.json
```
