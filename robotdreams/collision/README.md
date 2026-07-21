# PuppyBot final2 collider evidence

`final2-link-collider-manifest.v1.json` is the versioned, reviewable record of
every visual geometry source in the canonical final2 URDF. It is candidate
evidence only: it does not approve a collider for hardware or install one in a
RobotDreams scene.

Regenerate it from the PuppyBot repository root with:

```sh
python3 puppybot/scenarios/generate_final2_collision_manifest.py
```

The script resolves only `package://final2/` URIs into the canonical model
directory, preserves each URDF visual's translation, RPY rotation, and scale,
and sends GLTF/GLB candidates through PGE's public per-link collision API.
The checked-in report retains the PGE provenance and conservative reviewed
primitive profile for each generated visual. Any missing, unsupported, or
generation-failed visual remains explicitly blocked in the same manifest.

Before a candidate becomes a runtime collider, a reviewer must select it and
validate it in the intended dynamic RobotDreams scene. In particular, no
generated candidate is evidence for mass, friction, collision groups, motor
parameters, or real hardware dimensions.
