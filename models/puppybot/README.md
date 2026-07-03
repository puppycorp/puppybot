# PuppyBot RobotDreams Model

Reusable RobotDreams asset for the full PuppyBot rover base plus arm.

```text
models/puppybot/robotdreams.json
models/puppybot/final2/urdf/final2.urdf
```

RobotDreams scenes should reference this asset instead of copying the URDF and meshes into scene folders.

The model profile records the semantic arm joint mapping and the current frame mapping. PuppyBot core uses ROS-style `X forward`, `Y left`, `Z up`; this CAD export uses model `+Y` as physical up.

The semantic arm joints follow the full PuppyBot TCP ancestor chain:
`revolute_2_3` yaw, `revolute_1_1` shoulder, `revolute_1_2` elbow, and
`revolute_1` wrist. The TCP is attached to `part_1_4`.
