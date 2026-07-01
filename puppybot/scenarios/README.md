# PuppyBot Scenarios

Scenario scripts are host-side "brain process" harnesses. They should talk to
the same interfaces the real robot uses:

- PuppyBot Rust runtime WebSocket API for robot control.
- RobotDreams virtual STServo bus for simulated servo hardware.
- A camera/video device for perception.
- Scenario sensor inputs for completion checks, such as a bin pressure sensor.
- RobotDreams scenario telemetry for semantic task progress.

`place_ball_to_bin.robotdreams.json` is the RobotDreams scenario definition for
the task. The Python harness loads it with `robotdreams scenario load`, then
resets, observes, and exports sensors through the same first-class scenario
command group.

The current scripts use scripted policy while the video/perception side is being
connected. The intended next step is a RobotDreams virtual webcam device that a
Python brain can open exactly like a physical camera.

## Completion Sensors

`place_ball_to_bin.py` waits for a bin pressure signal before marking the
scenario complete. By default, it asks RobotDreams to export the virtual
`bin_pressure` sensor to `/tmp/robotdreams-bin-pressure.json`.

For a real external harness, override the source file:

```sh
python3 scenarios/place_ball_to_bin.py --bin-pressure-file /tmp/bin-pressure.json
```

The file can contain `true`, `1`, `pressed`, or JSON such as:

```json
{"pressed": true}
```

or:

```json
{"pressure": 0.82}
```

If no pressure file is provided, the scenario uses RobotDreams' exported virtual
pressure sensor.

During a run, the script posts task observations to RobotDreams after each
major robot action and prints the resulting scenario progress. Expected progress
values include `seekingBall`, `grasped`, `carrying`, `pressureDetected`, and
`complete`.

## Run Artifacts

Use `--recording-dir` to save machine-readable proof for a deterministic E2E
run:

```sh
python3 scenarios/place_ball_to_bin.py --recording-dir workdir/recordings/place-ball-to-bin-001
```

The directory contains:

- `run.json`
- `scenario.json`
- `progress.jsonl`
- `robot_commands.jsonl`
- `sensor.jsonl`
- `completion.json`
- `validation.json`

`validation.json` is intentionally conservative: it can mark the run usable as a
deterministic E2E test while still marking `usableAsMotionProof` false until
RobotDreams-derived motion/video evidence is available.
