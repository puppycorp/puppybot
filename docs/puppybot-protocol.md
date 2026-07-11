# Puppybot WebSocket Protocol

The supported transport is WebSocket at `/ws`, advertised on local networks as
`_ws._tcp`. The current Rust firmware and runtime do not expose this protocol
over Bluetooth; the Bluetooth mode retained in the Android app is unsupported.

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
| `0x06` | reserved | retired; do not reuse |
| `0x07` | `SMARTBUS_SCAN` | retired; unhandled by the current Rust stack |
| `0x08` | `SMARTBUS_SET_ID` | retired; unhandled by the current Rust stack |
| `0x09` | `SET_MOTOR_POLL` | `count:u8`, `servo_ids:[u8;count]`; legacy telemetry subscription |
| `0x0A` | `SET_BOT_ID` | retired; unhandled by the current Rust stack |
| `0x0B` | `ARM_MOVE` | retired; unhandled by the current Rust stack |
| `0x0C` | `ARM_SET_SPEED` | `speed:u16le` |
| `0x0D` | `ARM_JOG` | `joint:u8`, `direction:i8`, `speed:u16le` |
| `0x0E` | `ARM_STOP_JOINT` | `joint:u8` |
| `0x0F` | `ARM_STOP_ALL` | empty |
| `0x10` | `ARM_GOTO_TICKS` | `speed:u16le`, `ticks:[i32le;4]` |
| `0x11` | `ARM_GOTO_ANGLES` | `speed:u16le`, `angles_deg:[f32le;4]` |
| `0x12` | `ARM_GOTO_COORDS` | `speed:u16le`, `x:f32le`, `y:f32le`, `z:f32le`, `tool_phi_deg:f32le` |
| `0x13` | `ARM_HOLD` | `speed:u16le` |
| `0x14` | `ARM_SET_JOINT_TICK` | `joint:u8`, `speed:u16le`, `tick:i32le` |
| `0x15` | `ARM_SET_TICK_LIMITS` | `joint:u8`, `min:i32le`, `max:i32le` |
| `0x16` | `ARM_SET_TICK_LIMITS_ENABLED` | `joint:u8`, `enabled:u8` |
| `0x17` | `ARM_MOVE_RELATIVE` | `speed:u16le`, `frame:u8`, `dx_mm:f32le`, `dy_mm:f32le`, `dz_mm:f32le` |
| `0x18` | `ARM_CLEAR_FAULTS` | `joint:u8`; `0xFF` or an empty payload means all joints |
| `0x19` | `CONFIG_GET` | empty |
| `0x1A` | `CONFIG_SET` | `version:u8`, `steering_servo_id:u8`, `arm_servo_ids:[u8;4]` |
| `0x1B` | `DRIVE_STEER` | `throttle:i8`, `steering:i8`, each `-100..100` |
| `0x1C` | `STOP_DRIVE` | empty |
| `0x1D` | `ARM_JOINT` | `joint:u8`, `angle_deg:i16le`, `speed:u16le` |
| `0x1E` | `ARM_POSE` | `x:f32le`, `y:f32le`, `z:f32le`, `wrist_deg:f32le`, `speed:u16le` |
| `0x1F` | `ARM_STOP` | empty |
| `0x20` | `SERVO_SET` | `servo_id:u8`, `angle_deg:u16le`, `duration_ms:u16le` |
| `0x21` | `SUBSCRIBE` | `topic:u8`, `enabled:u8`; topic `0x01` is arm state |
| `0x22` | `ARM_START_TCP_JOG` | `frame:u8`, `direction:[f32le;3]`, `speed_mm_s:f32le` |
| `0x23` | `ARM_STOP_TCP_JOG` | empty |

`ARM_MOVE_RELATIVE` moves the arm tool center point from its current pose and
preserves the current tool pitch. Frame `0x00` is base/table frame; frame `0x01`
is tool frame. In base frame, `dz_mm` is table-up millimeters. In tool frame,
`dx_mm` follows the gripper approach axis, `dy_mm` is tool-left, and `dz_mm` is
the derived tool-up axis. Non-finite deltas are rejected. Speeds above
`i16::MAX` are clamped for this command before reaching the arm controller.

## Messages

| ID | Name | Payload |
| ---: | --- | --- |
| `0x01` | `PONG` | empty |
| `0x07` | `ARM_STATE` | `joint_count:u8`, repeated joint telemetry, current-coordinate block, target extension |
| `0x08` | `CONFIG_STATE` | `config_version:u8`, `steering_servo_id:u8`, `arm_servo_ids:[u8;4]` |

Arm joint telemetry is:

| Field | Type |
| --- | --- |
| servo id | `u8` |
| flags | `u8`; bit `0x01` online, `0x02` feedback, `0x04` limit, `0x08` target tick, `0x10` fault present |
| tick | `i32le` |
| target tick | `i32le` |
| speed | `i16le` |
| limit min | `i32le` |
| limit max | `i32le` |
| angle degrees | `f32le` |
| fault length | `u8` |
| fault | UTF-8 bytes |

The repeated joint records are followed by a fixed-size current-coordinate
block. It is always present:

| Field | Type |
| --- | --- |
| flags | `u8`; bit `0x01` means the coordinates are valid |
| x millimeters | `f32le`; zero when invalid |
| y millimeters | `f32le`; zero when invalid |
| z millimeters | `f32le`; zero when invalid |

The current-coordinate block is followed by target extension tag `0x01`. For
each joint, in the same order as the main joint records, the extension then
contains:

| Field | Type |
| --- | --- |
| flags | `u8`; bit `0x01` means the target angle is valid |
| target angle degrees | `f32le`; zero when invalid |

After all per-joint target-angle entries, a fixed-size target-coordinate block
completes the message:

| Field | Type |
| --- | --- |
| flags | `u8`; bit `0x01` means the target coordinates are valid |
| target x millimeters | `f32le`; zero when invalid |
| target y millimeters | `f32le`; zero when invalid |
| target z millimeters | `f32le`; zero when invalid |

Clients that only understand the original arm-state shape may stop after the
fixed current-coordinate block. Current clients should consume extension tag
`0x01`, exactly `joint_count` target-angle entries, and the final target block.
