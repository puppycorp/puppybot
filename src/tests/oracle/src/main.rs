use std::io::{self, Read, Write};

use puppybot_core::{
    config::{ConfigError, JointCalibration, PuppybotConfigV1},
    drive::DriveCommand,
    protocol::ProtocolEvent,
    puppyarm::{
        puppyarm::PuppyArm,
        servo_safety::SafetyFault,
        types::{ArmCommand, ArmMode, ControllerError, TcpFrame},
    },
    robot::Puppybot,
    stservo::{
        Mode, StServo, build_packet,
        mock::{FakeSerialBus, FakeServo},
    },
};

fn fault(f: Option<SafetyFault>) -> u64 {
    match f {
        None => 0,
        Some(SafetyFault::OverTemperature) => 1,
        Some(SafetyFault::FeedbackUnavailable) => 2,
        Some(SafetyFault::FeedbackStale) => 3,
        Some(SafetyFault::Stall) => 4,
        Some(SafetyFault::DeadmanFeedbackStale) => 5,
        Some(SafetyFault::DeadmanCommandStale) => 6,
    }
}

fn result(result: Result<(), ControllerError>) -> Vec<u64> {
    vec![match result {
        Ok(()) => 0,
        Err(ControllerError::InvalidJoint) => 1,
        Err(ControllerError::InvalidServoIds) => 2,
        Err(ControllerError::InvalidLimit) => 3,
        Err(ControllerError::MissingFeedback) => 4,
        Err(ControllerError::Ik(_)) => 5,
        Err(ControllerError::CartesianJointLimits(_)) => 6,
    }]
}

fn config_error(error: ConfigError) -> u64 {
    match error {
        ConfigError::UnsupportedVersion => 1,
        ConfigError::EmptySerial => 2,
        ConfigError::InvalidSerial => 3,
        ConfigError::InvalidDrive => 4,
        ConfigError::InvalidServoId => 5,
        ConfigError::DuplicateServoId => 6,
        ConfigError::InvalidTickRange => 7,
        ConfigError::InvalidSign => 8,
        ConfigError::InvalidReferenceAngle => 9,
        ConfigError::InvalidCoordinateRotation => 10,
    }
}

fn frame(n: u64) -> TcpFrame {
    match n {
        0 => TcpFrame::Base,
        1 => TcpFrame::Tool,
        2 => TcpFrame::YawFlat,
        _ => panic!("invalid oracle frame"),
    }
}

fn command(id: u64, a: &[u64]) -> ArmCommand {
    let f = |i: usize| f64::from_bits(a[i]);
    match id {
        1 => ArmCommand::SetSpeed(a[0] as i16),
        2 => ArmCommand::Spin {
            joint: a[0] as usize,
            direction: a[1] as i8,
        },
        3 => ArmCommand::Stop {
            joint: a[0] as usize,
        },
        4 => ArmCommand::StopAll,
        5 => ArmCommand::GotoTicks(std::array::from_fn(|i| a[i] as i32)),
        6 => ArmCommand::GotoAngles(std::array::from_fn(f)),
        7 => ArmCommand::GotoCoords {
            x: f(0),
            y: f(1),
            z: f(2),
            tool_phi_rad: f(3),
        },
        8 => ArmCommand::MoveTcp {
            frame: frame(a[0]),
            dx_mm: f(1),
            dy_mm: f(2),
            dz_mm: f(3),
        },
        9 => ArmCommand::StartTcpJog {
            frame: frame(a[0]),
            direction: [f(1), f(2), f(3)],
        },
        10 => ArmCommand::StartTcpJogAtSpeed {
            frame: frame(a[0]),
            direction: [f(1), f(2), f(3)],
            speed_mm_s: f(4),
        },
        11 => ArmCommand::StopTcpJog,
        12 => ArmCommand::Hold,
        13 => ArmCommand::SetJointTick {
            joint: a[0] as usize,
            tick: a[1] as i32,
        },
        14 => ArmCommand::SetJointAngle {
            joint: a[0] as usize,
            angle_rad: f(1),
        },
        15 => ArmCommand::SetJointReference {
            joint: a[0] as usize,
            tick: a[1] as i32,
            angle_rad: f(2),
        },
        16 => ArmCommand::SetServoAngle {
            servo_id: a[0] as u8,
            angle_rad: f(1),
            speed: a[2] as i16,
        },
        17 => ArmCommand::SetTickLimits {
            joint: a[0] as usize,
            min: a[1] as i32,
            max: a[2] as i32,
        },
        18 => ArmCommand::SetTickLimitsEnabled {
            joint: a[0] as usize,
            enabled: a[1] != 0,
        },
        19 => ArmCommand::ClearFaults {
            joint: (a[0] != u64::MAX).then_some(a[0] as usize),
        },
        20 => ArmCommand::SetServoIds(std::array::from_fn(|i| a[i] as u8)),
        _ => panic!("invalid oracle command"),
    }
}

fn frame_word(frame: TcpFrame) -> u64 {
    match frame {
        TcpFrame::Base => 0,
        TcpFrame::Tool => 1,
        TcpFrame::YawFlat => 2,
    }
}

fn event_words(event: ProtocolEvent) -> [u64; 6] {
    let mut out = [0; 6];
    let (id, values): (u64, Vec<u64>) = match event {
        ProtocolEvent::Drive(DriveCommand::DriveSteer { throttle, steering }) => {
            (101, vec![throttle as u64, steering as u64])
        }
        ProtocolEvent::Drive(DriveCommand::SetMotorSpeed { motor_id, speed }) => {
            (102, vec![motor_id as u64, speed as u64])
        }
        ProtocolEvent::Drive(DriveCommand::StopMotor { motor_id }) => {
            (102, vec![motor_id as u64, 0])
        }
        ProtocolEvent::Drive(DriveCommand::Stop) => (103, vec![]),
        ProtocolEvent::Drive(DriveCommand::SetSteeringServoId(id)) => (104, vec![id as u64]),
        ProtocolEvent::Arm(command) => match command {
            ArmCommand::SetSpeed(speed) => (1, vec![speed as u64]),
            ArmCommand::Spin { joint, direction } => (2, vec![joint as u64, direction as u64]),
            ArmCommand::Stop { joint } => (3, vec![joint as u64]),
            ArmCommand::StopAll => (4, vec![]),
            ArmCommand::GotoTicks(ticks) => (5, ticks.map(|v| v as u64).to_vec()),
            ArmCommand::GotoAngles(angles) => (6, angles.map(f64::to_bits).to_vec()),
            ArmCommand::GotoCoords {
                x,
                y,
                z,
                tool_phi_rad,
            } => (7, [x, y, z, tool_phi_rad].map(f64::to_bits).to_vec()),
            ArmCommand::MoveTcp {
                frame: f,
                dx_mm,
                dy_mm,
                dz_mm,
            } => (
                8,
                vec![
                    frame_word(f),
                    dx_mm.to_bits(),
                    dy_mm.to_bits(),
                    dz_mm.to_bits(),
                ],
            ),
            ArmCommand::StartTcpJogAtSpeed {
                frame: f,
                direction,
                speed_mm_s,
            } => (
                10,
                vec![
                    frame_word(f),
                    direction[0].to_bits(),
                    direction[1].to_bits(),
                    direction[2].to_bits(),
                    speed_mm_s.to_bits(),
                ],
            ),
            ArmCommand::StopTcpJog => (11, vec![]),
            ArmCommand::Hold => (12, vec![]),
            ArmCommand::SetJointTick { joint, tick } => (13, vec![joint as u64, tick as u64]),
            ArmCommand::SetJointAngle { joint, angle_rad } => {
                (14, vec![joint as u64, angle_rad.to_bits()])
            }
            ArmCommand::SetServoAngle {
                servo_id,
                angle_rad,
                speed,
            } => (16, vec![servo_id as u64, angle_rad.to_bits(), speed as u64]),
            ArmCommand::SetTickLimits { joint, min, max } => {
                (17, vec![joint as u64, min as u64, max as u64])
            }
            ArmCommand::SetTickLimitsEnabled { joint, enabled } => {
                (18, vec![joint as u64, enabled as u64])
            }
            ArmCommand::ClearFaults { joint } => (19, vec![joint.map_or(u64::MAX, |v| v as u64)]),
            ArmCommand::SetServoIds(ids) => (20, ids.map(u64::from).to_vec()),
            _ => panic!("unexpected protocol event"),
        },
    };
    out[0] = id;
    out[1..1 + values.len()].copy_from_slice(&values);
    out
}

fn mode(arm: &PuppyArm) -> u64 {
    match arm.mode() {
        ArmMode::Idle => 0,
        ArmMode::Jogging { .. } => 1,
        ArmMode::TrackingTicks { .. } => 2,
        ArmMode::TcpJogging { .. } => 3,
        ArmMode::Holding { .. } => 4,
        ArmMode::Fault => 5,
    }
}

fn mode_words(arm: &PuppyArm) -> Vec<u64> {
    match arm.mode() {
        ArmMode::Idle => vec![0],
        ArmMode::Jogging { joint, direction } => vec![1, joint as u64, direction as u64],
        ArmMode::TrackingTicks { targets } => {
            let mut out = vec![2];
            out.extend(targets.map(|v| v as u64));
            out
        }
        ArmMode::TcpJogging {
            frame,
            direction,
            speed_override_mm_s,
            last_step_ms,
            target_angles,
            target_coords_mm,
            tool_pitch_rad,
        } => {
            let mut out = vec![3, frame_word(frame)];
            out.extend(direction.map(f64::to_bits));
            out.extend([
                speed_override_mm_s.is_some() as u64,
                speed_override_mm_s.unwrap_or(0.0).to_bits(),
                last_step_ms,
            ]);
            out.extend(target_angles.map(f64::to_bits));
            out.extend(target_coords_mm.map(f64::to_bits));
            out.push(tool_pitch_rad.to_bits());
            out
        }
        ArmMode::Holding { targets } => {
            let mut out = vec![4];
            out.extend(targets.map(|v| v as u64));
            out
        }
        ArmMode::Fault => vec![5],
    }
}

fn snapshot(robot: &Puppybot) -> Vec<u64> {
    let mut out = vec![mode(&robot.arm)];
    let d = robot.drive_output();
    out.extend([
        d.left_motor_id as u64,
        d.right_motor_id as u64,
        d.steering_servo_id as u64,
        d.left_speed as u64,
        d.right_speed as u64,
        d.steering_angle_deg as u64,
        d.active as u64,
    ]);
    let p = robot.protocol_state();
    out.push(p.telemetry_enabled as u64);
    out.push(p.config.steering_servo_id as u64);
    out.extend(p.config.arm_servo_ids.map(u64::from));
    for j in robot.arm.joints {
        out.extend([
            j.servo_id as u64,
            j.tick_min as u64,
            j.tick_max as u64,
            j.raw_tick_min as u64,
            j.raw_tick_max as u64,
            j.sign.to_bits(),
            j.drive_sign as u64,
            j.reference_tick as u64,
            j.reference_angle_rad.to_bits(),
            j.zero_offset_rad.to_bits(),
            j.online as u64,
            j.has_feedback as u64,
            j.tick.is_some() as u64,
            j.tick.unwrap_or(0) as u64,
            j.angle_rad.is_some() as u64,
            j.angle_rad.unwrap_or(0.0).to_bits(),
            j.target_tick.is_some() as u64,
            j.target_tick.unwrap_or(0) as u64,
            j.target_angle_rad.is_some() as u64,
            j.target_angle_rad.unwrap_or(0.0).to_bits(),
            j.tick_delta as u64,
            j.limit_enabled as u64,
            j.speed as u64,
            j.last_feedback_ms,
            j.temp_c.is_some() as u64,
            j.temp_c.unwrap_or(0) as u64,
            j.last_sent_speed.is_some() as u64,
            j.last_sent_speed.unwrap_or(0) as u64,
            j.last_speed_cmd_ms,
            j.stall_since_ms.is_some() as u64,
            j.stall_since_ms.unwrap_or(0),
            fault(j.fault),
        ]);
    }
    let bytes = robot.arm_state_frame();
    out.push(bytes.len() as u64);
    out.extend(bytes.into_iter().map(u64::from));
    out
}

fn block_on<F: std::future::Future>(future: F) -> F::Output {
    let mut future = std::pin::pin!(future);
    let mut context = std::task::Context::from_waker(std::task::Waker::noop());
    loop {
        if let std::task::Poll::Ready(value) = future.as_mut().poll(&mut context) {
            return value;
        }
        std::thread::sleep(std::time::Duration::from_millis(1));
    }
}

fn execute(
    robot: &mut Puppybot,
    servo: &mut StServo<FakeSerialBus>,
    queue: &mut Vec<ProtocolEvent>,
    op: u64,
    a: &[u64],
) -> Vec<u64> {
    match op {
        0 => {
            *robot = Puppybot::new(a[0]);
            *servo = StServo::new(FakeSerialBus::new());
            queue.clear();
            vec![]
        }
        1 => result(robot.arm.try_handle_arm_cmd(command(a[1], &a[2..]), a[0])),
        2 => {
            robot.arm.record_feedback(a[1] as usize, a[2] as u16, a[0]);
            vec![]
        }
        3 => {
            let commands = robot.arm.update(a[0]);
            commands
                .into_iter()
                .flat_map(|c| [c.servo_id as u64, c.speed as u64, c.should_send as u64])
                .collect()
        }
        4 => {
            robot.arm.record_feedback_error(a[0] as usize);
            vec![]
        }
        5 => {
            robot
                .arm
                .record_temperature(a[0] as usize, (a[1] != 0).then_some(a[2] as u8));
            vec![]
        }
        6 => {
            robot.arm.record_wheel_speed_result(
                a[1] as usize,
                a[2] as u8,
                a[3] as i16,
                a[4] != 0,
                a[0],
            );
            vec![]
        }
        7 => {
            robot.arm.record_set_mode_result(
                a[0] as usize,
                a[1] as u8,
                if a[2] != 0 {
                    Mode::Wheel
                } else {
                    Mode::Position
                },
                a[3] != 0,
            );
            vec![]
        }
        8 => {
            let bytes: Vec<u8> = a[1..].iter().map(|v| *v as u8).collect();
            let p = robot.handle_frame(&bytes, a[0]);
            let bytes = p.response.unwrap_or_default();
            let mut out = vec![bytes.len() as u64];
            out.extend(bytes.into_iter().map(u64::from));
            out.push(p.events.len() as u64);
            for event in p.events {
                out.extend(event_words(event));
            }
            out
        }
        9 => snapshot(robot),
        10 => {
            robot.tick(0, a[0]);
            vec![]
        }
        11 => {
            let mut config = PuppybotConfigV1::default();
            for i in 0..4 {
                let j = &a[1 + i * 8..];
                config.arm.joints[i] = JointCalibration {
                    servo_id: j[0] as u8,
                    tick_min: j[1] as i32,
                    tick_max: j[2] as i32,
                    reference_tick: j[3] as i32,
                    reference_angle_rad: f64::from_bits(j[4]),
                    angle_sign: j[5] as i8,
                    drive_sign: j[6] as i8,
                    limit_enabled: j[7] != 0,
                };
            }
            let error = match Puppybot::new_with_config(&config, a[0]) {
                Ok(new) => {
                    *robot = new;
                    0
                }
                Err(_) => 1,
            };
            vec![error]
        }
        12 => vec![
            robot
                .arm
                .begin_wheel_mode_attempt(a[1] as usize, a[2] as u8, a[0], a[3] != 0)
                as u64,
        ],
        13 => vec![robot.arm.wheel_mode_ready(a[0] as usize, a[1] as u8) as u64],
        14 => vec![robot.arm.take_initialize_wheel_mode() as u64],
        15 => {
            let params: Vec<u8> = a[2..].iter().map(|v| *v as u8).collect();
            let mut bytes = [0; 256];
            let n = build_packet(&mut bytes, a[0] as u8, a[1] as u8, &params).unwrap();
            bytes[..n].iter().map(|v| *v as u64).collect()
        }
        16 => {
            let r = puppybot_core::puppyarm::kinematics::ik_with_tool_pitch_branches(
                f64::from_bits(a[0]),
                f64::from_bits(a[1]),
                f64::from_bits(a[2]),
                f64::from_bits(a[3]),
            );
            r.into_iter()
                .flat_map(|r| {
                    [
                        r.yaw.to_bits(),
                        r.shoulder.to_bits(),
                        r.elbow.to_bits(),
                        r.wrist.to_bits(),
                        r.reachable as u64,
                    ]
                })
                .collect()
        }
        17 => {
            let r = puppybot_core::puppyarm::kinematics::fk(
                f64::from_bits(a[0]),
                f64::from_bits(a[1]),
                f64::from_bits(a[2]),
                f64::from_bits(a[3]),
            );
            vec![r.0.to_bits(), r.1.to_bits(), r.2.to_bits()]
        }
        18 => vec![(f32::from_bits(a[0] as u32) as f64).to_bits()],
        19 => vec![(f64::from_bits(a[0]) as f32).to_bits() as u64],
        20 => {
            servo
                .bus_mut()
                .set_servo(FakeServo::new(a[0] as u8, a[1] as u16));
            vec![]
        }
        21 => {
            let bus = servo.bus_mut();
            let id = a[0] as u8;
            match a[1] {
                0 => bus.set_online(id, a[2] != 0),
                2 => bus.set_position(id, a[2] as u16),
                4 => bus.set_read_failure(id, a[2] != 0),
                5 => bus.set_write_failure(id, a[2] != 0),
                _ => panic!("invalid fake mutation"),
            }
            vec![]
        }
        22 => {
            let mut events = std::mem::take(queue).into_iter();
            servo.bus_mut().writes.clear();
            block_on(robot.run_once(servo, a[0], || events.next()));
            servo
                .bus()
                .writes
                .iter()
                .flat_map(|packet| {
                    let mut bytes = (packet.len() as u16).to_le_bytes().to_vec();
                    bytes.extend(packet);
                    bytes.into_iter().map(u64::from)
                })
                .collect()
        }
        23 => {
            if queue.len() >= 16 {
                return vec![(-11i64) as u64];
            }
            let event = match a[0] {
                101 => ProtocolEvent::Drive(DriveCommand::DriveSteer {
                    throttle: a[1] as i8,
                    steering: a[2] as i8,
                }),
                102 => ProtocolEvent::Drive(DriveCommand::SetMotorSpeed {
                    motor_id: a[1] as u8,
                    speed: a[2] as i8,
                }),
                103 => ProtocolEvent::Drive(DriveCommand::Stop),
                104 => ProtocolEvent::Drive(DriveCommand::SetSteeringServoId(a[1] as u8)),
                id => ProtocolEvent::Arm(command(id, &a[1..])),
            };
            queue.push(event);
            vec![0]
        }
        24 => {
            let mut config = PuppybotConfigV1::default();
            config.version = a[0] as u16;
            for (i, byte) in a[1..5].iter().flat_map(|v| v.to_le_bytes()).enumerate() {
                config.serial[i] = byte;
            }
            config.drive.left_motor_id = a[5] as u8;
            config.drive.right_motor_id = a[6] as u8;
            config.drive.steering_servo_id = a[7] as u8;
            config.drive.steering_center_deg = a[8] as u16;
            config.drive.steering_range_deg = a[9] as u16;
            config.drive.command_timeout_ms = a[10];
            config.coordinate.forward_sign = a[16] as i8;
            config.coordinate.left_sign = a[17] as i8;
            config.coordinate.up_sign = a[18] as i8;
            config.coordinate.base_yaw_offset_deg = f64::from_bits(a[19]);
            config.coordinate.tcp_forward_sign = a[20] as i8;
            config.coordinate.tcp_left_sign = a[21] as i8;
            config.coordinate.tcp_up_sign = a[22] as i8;
            for i in 0..4 {
                let j = &a[24 + i * 8..];
                config.arm.joints[i] = JointCalibration {
                    servo_id: j[0] as u8,
                    tick_min: j[1] as i32,
                    tick_max: j[2] as i32,
                    reference_tick: j[3] as i32,
                    reference_angle_rad: f64::from_bits(j[4]),
                    angle_sign: j[5] as i8,
                    drive_sign: j[6] as i8,
                    limit_enabled: j[7] != 0,
                };
            }
            vec![config.validate().err().map_or(0, config_error)]
        }
        25 => mode_words(&robot.arm),
        26 => {
            let r = puppybot_core::puppyarm::kinematics::arm_chain_points(
                f64::from_bits(a[0]),
                f64::from_bits(a[1]),
                f64::from_bits(a[2]),
                f64::from_bits(a[3]),
            );
            [r.yaw, r.shoulder, r.elbow, r.wrist, r.tcp]
                .into_iter()
                .flatten()
                .map(f64::to_bits)
                .collect()
        }
        27 => {
            let r = puppybot_core::puppyarm::kinematics::tooltip_target_to_wrist_target(
                f64::from_bits(a[0]),
                f64::from_bits(a[1]),
                f64::from_bits(a[2]),
                f64::from_bits(a[3]),
            );
            vec![r.0.to_bits(), r.1.to_bits(), r.2.to_bits()]
        }
        _ => panic!("invalid oracle operation {op}"),
    }
}

fn main() -> io::Result<()> {
    let mut input = Vec::new();
    io::stdin().read_to_end(&mut input)?;
    let words: Vec<u64> = input
        .chunks_exact(8)
        .map(|c| u64::from_le_bytes(c.try_into().unwrap()))
        .collect();
    let mut robot = Puppybot::new(0);
    let mut servo = StServo::new(FakeSerialBus::new());
    let mut queue = Vec::new();
    let mut at = 0;
    let mut output = io::BufWriter::new(io::stdout().lock());
    while at < words.len() {
        let op = words[at];
        let count = words[at + 1] as usize;
        at += 2;
        let out = execute(
            &mut robot,
            &mut servo,
            &mut queue,
            op,
            &words[at..at + count],
        );
        at += count;
        output.write_all(&(out.len() as u64).to_le_bytes())?;
        for word in out {
            output.write_all(&word.to_le_bytes())?;
        }
    }
    output.flush()
}
