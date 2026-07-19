#!/usr/bin/env python3
"""Create deterministic, training-only RobotDreams bottle scene variants.

These JSON projects are inputs to `puppybot-runtime dataset-capture --sim`.
They are never passed to the autonomy policy, and their object transforms are
used only by the existing V4 capture-label path.
"""
from __future__ import annotations
import argparse, json, random
from pathlib import Path

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    args = parser.parse_args(); args.template = args.template.resolve(); args.output.mkdir(parents=True, exist_ok=True)
    puppybot = args.template.parents[2]; robotdreams = puppybot.parent / "RobotDreams"
    for seed in args.seeds:
        rng = random.Random(seed); project = json.loads(args.template.read_text())
        project["modelProfile"] = str((puppybot / "models/puppybot/robotdreams.json").resolve())
        project["robots"][0]["model"]["path"] = str((puppybot / "models/puppybot/final2/urdf/final2.urdf").resolve())
        position = [rng.uniform(0.105, 0.175), rng.uniform(0.120, 0.180), 0.10]
        # Preserve the calibrated lying-bottle baseline while varying heading
        # and a small roll/tilt that remains above the floor.
        rotation = [rng.uniform(-0.10, 0.10), 1.57079633, rng.uniform(-0.70, 0.70)]
        scale = [rng.uniform(0.26, 0.34)] * 3
        for item in project["scene"]["objects"]:
            if item["id"] == "bottle":
                item.update({"position": position, "rotation": rotation, "scale": scale,
                             "asset": str((puppybot / "models/water-bottle.glb").resolve())})
            elif item["id"] == "trashbin": item["asset"] = str((robotdreams / "examples/trashbin.gltf").resolve())
        output = args.output / f"scene-{seed}.robotdreams.json"
        output.write_text(json.dumps(project, indent=2) + "\n")
        (args.output / f"scene-{seed}.provenance.json").write_text(json.dumps({"seed": seed, "bottle": {"position": position, "rotation": rotation, "scale": scale}}, indent=2) + "\n")
        print(output)
    return 0
if __name__ == "__main__": raise SystemExit(main())
