# PuppyBot

PuppyBot is a distributed robot platform powered by an ESP32-based body and an AI "brain" running on a PC or phone. The robot executes motor, sensor, and actuator instructions sent in a compact binary protocol designed for real-time performance and parallel task execution.

## Development

**server**

```
bun install
bun run start
```

**esp32**

Requires ESP-idf sdk either install it your self.

First create a `.env` file in the `esp32` directory. The `esp32/build.sh` script will source this file, making the variables available to the build system.

Example `.env` file:
```
# Optional: semicolon-separated list of "SSID:password" pairs.
# Example: WIFI_CREDENTIALS="Home WiFi:supersecret;Phone Hotspot:backuppass"
# For a single network, provide just one pair.
WIFI_CREDENTIALS=
VERSION=NUMBER
PUPPY_VARIANT=STRING
# Optional: server host for the bot to connect to.
SERVER_HOST=your.server.host
# Optional: device ID for the bot.
DEVICE_ID=1
```

```
git submodule update --init --recursive
./deps/espidf/install.sh
. ./deps/espidf/export.sh
./esp32/build.sh
```

**android**

Open android folder with android studio and run.

## ESP32 Wiring Guide

The firmware expects an ESP32-DevKit-style board driving two DC motors through an
H-bridge and up to four hobby servos. Wire the control electronics before
flashing the firmware so the boot calibration routine can centre each actuator.

### Power and common ground

- Power the ESP32 from USB or a regulated 5 V rail that can supply at least
  500 mA.
- Feed the H-bridge driver and servos from a dedicated motor supply sized for
  your hardware.
- Tie the grounds of the ESP32, motor driver and servo supply together to give
  the PWM signals a common reference.

### DC motor driver pins

Connect the direction and PWM inputs of your dual H-bridge (for example, an
L298N or TB6612 breakout) to the ESP32 pins shown below. The `INx` signals set
motor direction and the `ENx` pins carry the 1 kHz PWM drive from the firmware.

| Function                        | ESP32 GPIO |
| ------------------------------- | ---------- |
| Left motor direction A (`IN1`)  | 25         |
| Left motor direction B (`IN2`)  | 26         |
| Left motor enable (`ENA`)       | 33         |
| Right motor direction A (`IN3`) | 27         |
| Right motor direction B (`IN4`) | 14         |
| Right motor enable (`ENB`)      | 32         |

### Servo headers

Four 3-pin servo headers provide 50 Hz PWM outputs. Supply 5 V and ground to the
servo rail, then connect the signal lines as shown:

| Servo ID | ESP32 GPIO | Typical usage     |
| -------- | ---------- | ----------------- |
| 0        | 13         | PuppyBot steering |
| 1        | 21         | PuppyArm shoulder |
| 2        | 22         | PuppyArm elbow    |
| 3        | 23         | PuppyArm gripper  |

The firmware automatically recentres each servo on boot using the variant’s
`puppy_servo_boot_angle` profile. Keep the robot clear of obstacles while it
initialises.

## Features

- Parallel task execution across motors, arms, grippers, and sensors
- Binary protocol for minimal latency over WebSocket/TCP
- Instruction interpreter on ESP32 for reactive real-time execution
- AI brain can dynamically generate, replace, or stop instructions

## Binary Protocol

### Frame Header (6 bytes)

| Byte(s) | Field          | Size (bytes) | Description                                       |
| ------- | -------------- | ------------ | ------------------------------------------------- |
| 0       | Start Byte     | 1            | Always 0xAA for version v1                        |
| 1       | Command Type   | 1            | Instruction type (e.g., 0x01 = SEND_INSTRUCTIONS) |
| 2–3     | Payload Length | 2            | Payload size in bytes (excluding header)          |
| 4-..    | Payload        | N            | How many bytes in the payload                     |

All multi-byte fields are little-endian.

#### Command Types

| Value | Command Name    | Description                       |
| ----- | --------------- | --------------------------------- |
| 0x01  | DRIVE_MOTOR     | Drive a motor.                    |
| 0x02  | STOP_MOTOR      | Stop a motor.                     |
| 0x03  | STOP_ALL_MOTORS | Stop all motors. No other payload |

### DRIVE_MOTOR

| Field     | Type  | Description                         |
| --------- | ----- | ----------------------------------- |
| MotorID   | uint8 | Target motor ID                     |
| type      | int8  | 0 = DC                              |
| speed     | int8  | -100% to 100%                       |
| steps     | int16 | Number of steps to move             |
| step_time | int16 | Time to wait between steps (micros) |

### Servo Outputs

The ESP32 firmware now exposes four MG90S-compatible servo outputs over the same binary protocol. Servo **0** remains the PuppyBot steering servo on **GPIO13**; servos **1**–**3** are routed to GPIO21, GPIO22 and GPIO23 for PuppyArm joints or other accessories. All servos share a 50 Hz PWM source and accept angles in the 0–180° range. Send `TURN_SERVO` commands over the WebSocket connection to position each servo independently in real time.

| Servo ID | GPIO | Typical usage     |
| -------- | ---- | ----------------- |
| 0        | 13   | PuppyBot steering |
| 1        | 21   | PuppyArm shoulder |
| 2        | 22   | PuppyArm elbow    |
| 3        | 23   | PuppyArm gripper  |

### Firmware variants

Set the `PUPPY_VARIANT` environment variable at build time to describe the hardware the firmware is targeting. The ESP32 build will default to `PUPPYBOT`, but you can switch to the PuppyArm profile—which adjusts the advertised mDNS identity and default servo centering—by exporting `PUPPY_VARIANT=puppyarm` before calling `idf.py`:

```bash
PUPPY_VARIANT=puppyarm idf.py build flash
```

Additional variants can be introduced by extending `esp32/main/variant_config.h`. The build system uppercases the value you provide and strips non-alphanumeric characters before exporting a matching preprocessor define (`PUPPY_VARIANT_<VALUE>`). Empty or unknown values fall back to `PUPPY_VARIANT_PUPPYBOT`.

| Variant  | `PUPPY_VARIANT` value | Hostname   | Servo count | Drive motors | Steering servo center | Notes                                                                                                           |
| -------- | --------------------- | ---------- | ----------- | ------------ | --------------------- | --------------------------------------------------------------------------------------------------------------- |
| PuppyBot | `puppybot` (default)  | `puppybot` | 4           | Yes          | 88°                   | Rover chassis; steering servo on GPIO13 is required, the remaining three headers are optional accessory servos. |
| PuppyArm | `puppyarm`            | `puppyarm` | 4           | No           | 90°                   | Arm-focused build; disables drive motors and recenters all servos.                                              |

Define additional variants by adding a new `VARIANT_*` entry and configuration block in `esp32/main/variant_config.h`, then set `PUPPY_VARIANT` to the lowercase variant key.

### TURN_SERVO

| Field   | Type  | Description                         |
| ------- | ----- | ----------------------------------- |
| servoId | uint8 | Servo index to control (0–3)        |
| angle   | int16 | Target angle for the servo (0–180°) |

### STOP_MOTOR

| Field   | Type  | Description     |
| ------- | ----- | --------------- |
| MotorID | uint8 | Target motor ID |
