# PuppyBot Circles

Renders a RobotDreams PuppyBot bin scene video with:

- an orbit camera at 45 degrees
- PuppyBot drive output produced from `puppybot_core::drive::DriveController`
- a circular drive path from turned steering
- PuppyArm elbow servo target animation
- MP4 encoding through `pge-video`

From the PuppyBot repository root:

```sh
cargo run --release --manifest-path examples/puppybot-circles/Cargo.toml -- \
  robotdreams/project.json \
  workdir/puppybot-circles.mp4 \
  160 90 24 1
```

The arguments are:

```text
<robotdreams-project> <output-mp4> <width> <height> <fps> <seconds>
```

The output video is encoded at the requested FPS. The current RobotDreams native renderer is CPU-bound, so wall-clock render throughput is much slower than 24 FPS until RobotDreams is connected to a GPU/WGPU renderer path.
