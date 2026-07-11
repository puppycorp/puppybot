# Puppybot WebSocket Protocol

Binary client commands use this frame:

| Offset | Size | Field |
| --- | ---: | --- |
| 0 | 1 | protocol version, currently `0x01` |
| 1 | 1 | command id |
| 2 | 2 | little-endian payload length |
| 4 | N | payload |

Binary server messages use this frame:

| Offset | Size | Field |
| --- | ---: | --- |
| 0 | 2 | little-endian protocol version, currently `0x0001` |
| 2 | 1 | message id |
| 3 | N | message payload |

## Commands

| ID | Name | Payload |
| ---: | --- | --- |
| `0x01` | `PING` | empty |
| `0x02` | `DRIVE_MOTOR` | legacy motor payload |
| `0x03` | `STOP_MOTOR` | legacy motor id |
| `0x04` | `STOP_ALL_MOTORS` | empty |
| `0x0D` | `ARM_JOG` | `joint:u8`, `direction:i8`, `speed:u16le` |
| `0x0E` | `ARM_STOP_JOINT` | `joint:u8` |
| `0x12` | `ARM_GOTO_COORDS` | `speed:u16le`, `x:f32le`, `y:f32le`, `z:f32le`, `tool_phi_deg:f32le` |
| `0x17` | `ARM_MOVE_RELATIVE` | `speed:u16le`, `frame:u8`, `dx_mm:f32le`, `dy_mm:f32le`, `dz_mm:f32le` |
| `0x19` | `CONFIG_GET` | empty |
| `0x1A` | `CONFIG_SET` | `version:u8`, `steering_servo_id:u8`, `arm_servo_ids:[u8;4]` |
| `0x1B` | `DRIVE_STEER` | `throttle:i8`, `steering:i8`, each `-100..100` |
| `0x1C` | `STOP_DRIVE` | empty |
| `0x1D` | `ARM_JOINT` | `joint:u8`, `angle_deg:i16le`, `speed:u16le` |
| `0x1E` | `ARM_POSE` | legacy `ARM_GOTO_COORDS` payload: `x:f32le`, `y:f32le`, `z:f32le`, `wrist_deg:f32le`, `speed:u16le` |
| `0x1F` | `ARM_STOP` | empty |
| `0x20` | `SERVO_SET` | `servo_id:u8`, `angle_deg:u16le`, `duration_ms:u16le` |
| `0x21` | `SUBSCRIBE` | `topic:u8`, `enabled:u8`; topic `0x01` is arm state |

`ARM_MOVE_RELATIVE` moves the arm tool center point from its current pose and
preserves the current tool pitch. Frame `0x00` is base/table frame; frame `0x01`
is tool frame. In base frame, `dz_mm` is table-up millimeters. In tool frame,
`dx_mm` follows the gripper approach axis, `dy_mm` is tool-left, and `dz_mm` is
the derived tool-up axis. Non-finite deltas are rejected. Speeds above
`i16::MAX` are clamped for this command before reaching the arm controller.

## Messages

| ID | Name | Payload |
| ---: | --- | --- |
| `0x02` | `PONG` | empty |
| `0x07` | `ARM_STATE` | `joint_count:u8`, repeated joint telemetry, optional coords |
| `0x08` | `CONFIG_STATE` | `config_version:u8`, `steering_servo_id:u8`, `arm_servo_ids:[u8;4]` |

Arm joint telemetry is:

| Field | Type |
| --- | --- |
| servo id | `u8` |
| flags | `u8`; bit `0x01` online, `0x02` feedback, `0x04` limit, `0x08` target |
| tick | `i32le` |
| target tick | `i32le` |
| speed | `i16le` |
| limit min | `i32le` |
| limit max | `i32le` |
| angle degrees | `f32le` |
| fault length | `u8` |
| fault | UTF-8 bytes |

If present, coordinates follow all joints as `flags:u8`, `x:f32le`, `y:f32le`, `z:f32le`. Coordinates are valid when bit `0x01` is set.
