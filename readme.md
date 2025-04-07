# PuppyBot

PuppyBot is a distributed robot platform powered by an ESP32-based body and an AI "brain" running on a PC or phone. The robot executes motor, sensor, and actuator instructions sent in a compact binary protocol designed for real-time performance and parallel task execution.

## Features

- Parallel task execution across motors, arms, grippers, and sensors
- Binary protocol for minimal latency over WebSocket/TCP
- Instruction interpreter on ESP32 for reactive real-time execution
- AI brain can dynamically generate, replace, or stop instructions

## Binary Protocol

### Frame Header (6 bytes)

| Byte(s) | Field          | Size (bytes) | Description                                      |
|---------|----------------|--------------|--------------------------------------------------|
| 0       | Start Byte     | 1            | Always 0xAA for version v1                      |
| 1       | Command Type   | 1            | Instruction type (e.g., 0x01 = SEND_INSTRUCTIONS)|
| 2–3     | Payload Length | 2            | Payload size in bytes (excluding header)        |
| 4–5     | Block Count    | 2            | Number of instruction blocks in the payload     |

All multi-byte fields are big-endian (network byte order).

#### Command Types

| Value  | Command Name      | Description                                   |
|--------|-------------------|-----------------------------------------------|
| 0x01   | SEND_INSTRUCTIONS | Send one or more instruction blocks           |
| 0x02   | STOP_ALL          | Stop all subsystems immediately               |
| 0x03   | REPLACE_BLOCK     | Replace instruction queue for a subsystem     |
| 0x04   | PAUSE_ALL         | Pause all execution                           |
| 0x05   | RESUME_ALL        | Resume all paused instructions                |
| 0x06   | QUERY_STATE       | Request current sensor and system status      |

### Instructions

#### SLEEP

Pause execution for a fixed number of milliseconds.

#### DRIVE_MOTOR

| Field    | Type   | Description                     |
|----------|--------|---------------------------------|
| MotorID  | uint8  | Target motor ID                 |
| speed    | int8   | Speed from -100 to 100          |
| amount   | uint16 | How many degrees/steps to move  |

#### STOP

Immediately stops a motor or all motors.

#### DO_UNTIL_CONDITION

Executes a single instruction repeatedly or once, until a condition becomes true.

| Field        | Type     | Description                          |
|--------------|----------|--------------------------------------|
| Type         | `uint8`  | `0x08`                               |
| Target ID    | `uint8`  | Subsystem to control                 |
| InnerInstrID | `uint8`  | Instruction to execute (e.g. DRIVE)  |
| InnerArgs    | variable | Arguments for the inner instruction  |
| Condition    | 5 bytes  | Condition frame                      |

### Condition Frame

**Operators**
| Field	 | Value | Description                                                      |
|--------|-------|------------------------------------------------------------------|
| `==`   | 0x00  |                                                                  |
| `!=`   | 0x01  |                                                                  |
| `>`    | 0x02  |                                                                  |
| `<`    | 0x03  |                                                                  |
| `>=`   | 0x04  |                                                                  |
| `<=`   | 0x05  |                                                                  |
| `&&`   | 0x06  |                                                                  |
| `\|\|`   | 0x07  |                                                                  |
| `Forever` | 0x08  | Reserved: condition never becomes true (run forever unless externally interrupted) |

> **Note**: The `Forever` operator (`0x08`) creates a condition that always evaluates as false. This causes the inner instruction to execute continuously until the robot receives a STOP or REPLACE command from the brain.

**Frame Structure**

| Field     | Type     | Description                                      |
|-----------|----------|--------------------------------------------------|
| Target ID | `uint8`  | e.g. motorX = `0x01`, system = `0xF0`            |
| Field ID  | `uint8`  | e.g. speed = `0x01`, time = `0x05`               |
| Operator  | `uint8`  | Type of the operator                             |
| Value     | `int16`  | Comparison threshold                             |  


### Parallel Instruction Blocks

Each block represents instructions for one subsystem (e.g., a motor, arm, gripper). These blocks are executed in parallel by the robot.

#### Block Layout

| Field              | Type   | Description                              |
|--------------------|--------|------------------------------------------|
| Target ID          | uint16 | Subsystem ID (e.g., motorX = 0x0001)     |
| Instruction Count  | uint8  | Number of instructions in the block      |
| Instructions       | variable | Serialized instructions (see below)    |

### Example: Set Servo to 90°

```plaintext
Instruction Type: SET_SERVO (0x03)
Subsystem ID: 0x0002
Pin: 5
Angle: 90

Full Message Frame:

Header:
0xAA 0x01 0x00 0x06  0x00 0x01
(Payload Length = 6, Block Count = 1)

Block:
0x00 0x02 0x01 0x03 0x05 0x5A
(Target ID = 0x0002, 1 instruction: SET_SERVO pin 5, angle 90)

Hex Dump:
AA 01 00 06 00 01
00 02 01 03 05 5A
```