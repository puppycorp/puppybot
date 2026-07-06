# PuppyBot Circles

Renders a RobotDreams PuppyBot bin scene video with:

- an orbit camera at 45 degrees
- PuppyBot drive output produced from `puppybot_core::drive::DriveController`
- a circular drive path from turned steering
- PuppyArm elbow joint animation
- headless WGPU rendering through `pge-wgpu-renderer`
- raw RGBA frame sequence MP4 encoding through `pge-video`

From the PuppyBot repository root:

```sh
cargo run --release --manifest-path examples/puppybot-circles/Cargo.toml -- \
  robotdreams/project.json \
  workdir/puppybot-circles.mp4 \
  320 180 24 10
```

The arguments are:

```text
<robotdreams-project> <output-mp4> <width> <height> <fps> <seconds>
```

The output video is encoded at the requested FPS. The example builds the full RobotDreams scene once, updates robot visual transforms incrementally while advancing RobotDreams rover drive kinematics from the PuppyBot drive command, and renders raw RGBA frames through PGE's headless WGPU renderer.
