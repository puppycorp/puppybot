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
| 4-..    | Payload    | N            | How many bytes in the payload                         |

All multi-byte fields are little-endian.

#### Command Types

| Value  | Command Name      | Description                                   |
|--------|-------------------|-----------------------------------------------|
| 0x01   | DRIVE_MOTOR       | Drive a motor.                                |
| 0x02   | STOP_MOTOR        | Stop a motor.                                 |
| 0x03   | STOP_ALL_MOTORS   | Stop all motors. No other payload                             |


### DRIVE_MOTOR

| Field    | Type   | Description                     |
|----------|--------|---------------------------------|
| MotorID  | uint8  | Target motor ID                 |
| type     | int8   | 0 = DC, 1 = Servo               |
| speed    | int8   | -100% to 100%                     |
| steps   | int16  | Number of steps to move         |
| step_time | int16  | Time to wait between steps (micros) |
| angle   | int16  | Angle to move (for servos)      |

### STOP_MOTOR

| Field    | Type   | Description                     |
|----------|--------|---------------------------------|
| MotorID  | uint8  | Target motor ID                 |
