# Experimental simulated visual stop

The isolated build in `prepare-sim-visual-stop.py` uses the same client binary
for both arms. `PUPPYBOT_SIM_VISUAL_STOP=1` enables the experimental stop;
`0` or omission leaves its behavior disabled. It runs only on the simulated
physical-agent protocol. It does not command a maneuver or resume afterward.

The detector observes the actor's resized RGB pixels, simulator camera tick,
and the previously acknowledged drive request. It never reads simulation
pose, object coordinates or contact as an actor input. Ten consecutive fresh
frames require nine non-deadband drive requests, forward or reverse; this is
a minimum 90 simulator ticks, or 1.8 simulated seconds at 20 ms per tick.
The time is not a wall-clock or physical stopping latency. If that image
window has insufficient texture, the client stops with an abstention reason;
if all adjacent images remain nearly unchanged after per-channel additive
brightness correction, it stops with an unconfirmed visual suspicion. Normal
image motion resets the stillness count. Detection is not a diagnosis of a
wall: periodic visual patterns and static occlusion can produce false flags.

The fixed integer detector resembles the prior offline candidate but is not
claimed identical. It uses linearly interpolated grayscale percentile ranks and
abstains at exactly 12 intensity levels to avoid a float32 rounding boundary;
it also stops on low texture even when pixels change. It needs separate
provenance-matched validation. No pose-based truth is fed back to it. The
separate auditor reads pose only after the simulator has finished.

A completed result requires the simulator to acknowledge the terminal stop
with zero commanded drive. Stale frames, bad drive echoes, stream failures,
timeouts or a missing/invalid stop acknowledgment can terminate the process
without a result; in those cases a stop is **not verified**. The peer-echoed
command is not physical motor feedback. No result here establishes real-robot
safety, traction, clearance or obstruction. The first prototype is stop-only;
any future reverse/turn experiment requires separate simulated clearance and
failure controls before consideration.

CPU tests compile the isolated client and use local fake simulator/policy
peers; they do not start a GPU. They cover textured stillness, simulated
forward and reverse requests, a periodic alias, low texture (including
percentile-boundary cases), dropped timing, invalid drive and stop replies,
and the matched disabled/enabled prefix. The output of the independent audit
is a check of recorded evidence, not authenticated camera origin or runtime.
