# Elephant Robotics adaptive gripper meshes

These glTF files are derived from the adaptive-gripper COLLADA meshes in
[`elephantrobotics/mycobot_ros`](https://github.com/elephantrobotics/mycobot_ros),
distributed under the BSD 2-Clause license in `LICENSE`.

Run `puppybot/scenarios/convert_collada_to_gltf.py` against the upstream
`mycobot_description/urdf/adaptive_gripper` directory to regenerate them. The
conversion bakes the COLLADA visual-scene transforms and millimetre unit scale
into metre-space glTF vertices for RobotDreams.
