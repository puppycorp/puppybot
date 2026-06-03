use embassy_sync::{blocking_mutex::raw::CriticalSectionRawMutex, channel::Channel};
use embassy_time::{Duration, Instant, Timer};
use esp_hal::{Blocking, uart::Uart};

use super::{
    controller::{ArmCommand, ArmController, ArmIntent, JOINT_COUNT},
    kinematics,
    servo_safety::SafetyFault,
};
use crate::stservo::{Mode, StServo};

const CONTROL_PERIOD: Duration = Duration::from_millis(20);
const TELEMETRY_PERIOD_MS: u64 = 100;
const ARM_WHEEL_ACC: u8 = 0;
const DIRECT_SERVO_ACC: u8 = 50;
const DIRECT_SERVO_SPEED: u16 = 2400;
const WHEEL_MODE_INIT_ATTEMPTS: usize = 3;
const WHEEL_MODE_INIT_RETRY: Duration = Duration::from_millis(50);
const WHEEL_MODE_RECOVERY_RETRY_MS: u64 = 1000;
const RAD_TO_DEG: f64 = 180.0 / core::f64::consts::PI;

pub type ServoController = StServo<Uart<'static, Blocking>>;
pub type IntentChannel = Channel<CriticalSectionRawMutex, PuppyarmIntent, 16>;
pub type TelemetryChannel = Channel<CriticalSectionRawMutex, PuppyarmTelemetry, 4>;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct WheelModeState {
    servo_ids: [u8; JOINT_COUNT],
    ready: [bool; JOINT_COUNT],
    last_attempt_ms: [u64; JOINT_COUNT],
}

impl WheelModeState {
    fn new(controller: &ArmController) -> Self {
        Self {
            servo_ids: core::array::from_fn(|index| controller.profiles[index].servo_id),
            ready: [false; JOINT_COUNT],
            last_attempt_ms: [0; JOINT_COUNT],
        }
    }

    fn sync_servo_ids(&mut self, controller: &ArmController) {
        for index in 0..JOINT_COUNT {
            let servo_id = controller.profiles[index].servo_id;
            if self.servo_ids[index] != servo_id {
                self.servo_ids[index] = servo_id;
                self.ready[index] = false;
                self.last_attempt_ms[index] = 0;
            }
        }
    }

    fn mark_ready(&mut self, index: usize) {
        if index < JOINT_COUNT {
            self.ready[index] = true;
        }
    }

    fn mark_not_ready(&mut self, index: usize) {
        if index < JOINT_COUNT {
            self.ready[index] = false;
        }
    }

    fn mark_all_not_ready(&mut self) {
        self.ready = [false; JOINT_COUNT];
        self.last_attempt_ms = [0; JOINT_COUNT];
    }

    fn mark_servo_not_ready(&mut self, servo_id: u8) {
        for index in 0..JOINT_COUNT {
            if self.servo_ids[index] == servo_id {
                self.ready[index] = false;
            }
        }
    }

    fn is_ready(&self, index: usize, servo_id: u8) -> bool {
        index < JOINT_COUNT && self.servo_ids[index] == servo_id && self.ready[index]
    }

    fn can_retry(&self, index: usize, now: u64) -> bool {
        index < JOINT_COUNT
            && now.saturating_sub(self.last_attempt_ms[index]) >= WHEEL_MODE_RECOVERY_RETRY_MS
    }

    fn mark_attempt(&mut self, index: usize, now: u64) {
        if index < JOINT_COUNT {
            self.last_attempt_ms[index] = now;
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PuppyarmTelemetry {
    pub seq: u32,
    pub joints: [PuppyarmJointTelemetry; JOINT_COUNT],
    pub coords_mm: Option<(f32, f32, f32)>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PuppyarmJointTelemetry {
    pub servo_id: u8,
    pub online: bool,
    pub has_feedback: bool,
    pub limit_reached: bool,
    pub tick: Option<i32>,
    pub target_tick: Option<i32>,
    pub speed: i16,
    pub limit_min: i32,
    pub limit_max: i32,
    pub angle_deg: Option<f32>,
    pub fault: Option<SafetyFault>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum PuppyarmIntent {
    Arm(ArmIntent),
    DirectServoSet {
        servo_id: u8,
        angle_deg: u16,
        speed: u16,
        acc: u8,
    },
    SteeringSet {
        servo_id: u8,
        angle_deg: u16,
        speed: u16,
        acc: u8,
    },
}

impl PuppyarmIntent {
    pub fn direct_servo_set(servo_id: u8, angle_deg: u16, speed: u16) -> Self {
        Self::DirectServoSet {
            servo_id,
            angle_deg,
            speed: if speed == 0 {
                DIRECT_SERVO_SPEED
            } else {
                speed
            },
            acc: DIRECT_SERVO_ACC,
        }
    }

    pub fn steering_set(servo_id: u8, angle_deg: u16) -> Self {
        Self::SteeringSet {
            servo_id,
            angle_deg,
            speed: DIRECT_SERVO_SPEED,
            acc: DIRECT_SERVO_ACC,
        }
    }
}

fn telemetry_snapshot(controller: &ArmController, seq: u32) -> PuppyarmTelemetry {
    let coords_mm = controller.current_coords().ok().map(|(x, y, z)| {
        (
            x as f32,
            y as f32,
            kinematics::shoulder_to_table_z(z) as f32,
        )
    });

    PuppyarmTelemetry {
        seq,
        joints: core::array::from_fn(|index| {
            let joint = controller.safety.joints[index];
            PuppyarmJointTelemetry {
                servo_id: joint.servo_id,
                online: joint.is_online,
                has_feedback: joint.has_feedback && joint.tick.is_some(),
                limit_reached: super::servo_safety::is_outside_limits(&joint),
                tick: joint.tick,
                target_tick: joint.target_tick,
                speed: joint.speed,
                limit_min: joint.tick_min,
                limit_max: joint.tick_max,
                angle_deg: controller
                    .joint_angle(index)
                    .ok()
                    .map(|angle_rad| (angle_rad * RAD_TO_DEG) as f32),
                fault: joint.fault,
            }
        }),
        coords_mm,
    }
}

fn publish_telemetry(
    telemetry: &'static TelemetryChannel,
    controller: &ArmController,
    seq: &mut u32,
    last_telemetry_ms: &mut u64,
    now: u64,
) {
    if now.saturating_sub(*last_telemetry_ms) < TELEMETRY_PERIOD_MS {
        return;
    }

    *last_telemetry_ms = now;
    *seq = seq.wrapping_add(1);

    let snapshot = telemetry_snapshot(controller, *seq);
    if telemetry.try_send(snapshot).is_err() {
        let _ = telemetry.try_receive();
        let _ = telemetry.try_send(snapshot);
    }
}

async fn ensure_wheel_mode(
    servo: &mut ServoController,
    wheel_modes: &mut WheelModeState,
    index: usize,
    servo_id: u8,
    now: u64,
    force: bool,
) -> bool {
    if wheel_modes.is_ready(index, servo_id) {
        return true;
    }

    if !force && !wheel_modes.can_retry(index, now) {
        return false;
    }

    wheel_modes.mark_attempt(index, now);
    match servo.set_mode(servo_id, Mode::Wheel).await {
        Ok(()) => {
            log::info!("wheel mode ready for arm servo {servo_id}");
            wheel_modes.mark_ready(index);
            true
        }
        Err(err) => {
            log::warn!("set wheel mode failed for servo {servo_id}: {:?}", err);
            wheel_modes.mark_not_ready(index);
            false
        }
    }
}

async fn initialize_wheel_mode(
    servo: &mut ServoController,
    controller: &ArmController,
    wheel_modes: &mut WheelModeState,
) {
    for (index, profile) in controller.profiles.iter().copied().enumerate() {
        let servo_id = profile.servo_id;
        for attempt in 1..=WHEEL_MODE_INIT_ATTEMPTS {
            if ensure_wheel_mode(
                servo,
                wheel_modes,
                index,
                servo_id,
                Instant::now().as_millis(),
                true,
            )
            .await
            {
                if let Err(err) = servo.write_wheel_speed(servo_id, 0, ARM_WHEEL_ACC).await {
                    log::warn!("initial wheel stop failed for servo {servo_id}: {:?}", err);
                    wheel_modes.mark_not_ready(index);
                }
                break;
            }

            if attempt < WHEEL_MODE_INIT_ATTEMPTS {
                Timer::after(WHEEL_MODE_INIT_RETRY).await;
            }
        }
    }
}

async fn apply_outputs(
    servo: &mut ServoController,
    controller: &mut ArmController,
    wheel_modes: &mut WheelModeState,
    now: u64,
) {
    let outputs = controller.update(now);
    for (index, output) in outputs.iter().copied().enumerate() {
        if !output.should_send {
            continue;
        }

        let force_wheel_mode = output.speed == 0;
        if !ensure_wheel_mode(
            servo,
            wheel_modes,
            index,
            output.servo_id,
            now,
            force_wheel_mode,
        )
        .await
        {
            continue;
        }

        if let Err(err) = servo
            .write_wheel_speed(output.servo_id, output.speed, ARM_WHEEL_ACC)
            .await
        {
            log::warn!(
                "set wheel speed failed for servo {} speed {}: {:?}",
                output.servo_id,
                output.speed,
                err
            );
            wheel_modes.mark_not_ready(index);
            continue;
        }

        let _ = controller.mark_speed_sent(index, output.speed, now);
    }
}

async fn read_feedback(
    servo: &mut ServoController,
    controller: &mut ArmController,
    wheel_modes: &mut WheelModeState,
    now: u64,
) {
    for index in 0..JOINT_COUNT {
        let servo_id = controller.profiles[index].servo_id;
        let was_online = controller.safety.joints[index].is_online;
        match servo.read_position(servo_id).await {
            Ok(tick) => {
                let _ = controller.record_feedback(index, tick as i32, now);
                if !was_online {
                    wheel_modes.mark_not_ready(index);
                }
            }
            Err(err) => {
                log::warn!("read position failed for servo {servo_id}: {:?}", err);
                let _ = controller.record_feedback_error(index);
                wheel_modes.mark_not_ready(index);
            }
        }
    }
}

async fn drain_intents(
    intents: &'static IntentChannel,
    controller: &mut ArmController,
    servo: &mut ServoController,
    wheel_modes: &mut WheelModeState,
    now: u64,
) {
    while let Ok(intent) = intents.try_receive() {
        match intent {
            PuppyarmIntent::Arm(command) => {
                if let ArmCommand::SetServoIds(_) = command {
                    if let Err(err) = controller.handle_command(command, now) {
                        log::warn!("arm intent rejected: {:?}", err);
                    }
                    wheel_modes.sync_servo_ids(controller);
                    wheel_modes.mark_all_not_ready();
                    initialize_wheel_mode(servo, controller, wheel_modes).await;
                    continue;
                }

                if let Err(err) = controller.handle_command(command, now) {
                    log::warn!("arm intent rejected: {:?}", err);
                }
            }
            PuppyarmIntent::DirectServoSet {
                servo_id,
                angle_deg,
                speed,
                acc,
            }
            | PuppyarmIntent::SteeringSet {
                servo_id,
                angle_deg,
                speed,
                acc,
            } => {
                if let Err(err) = servo.set_mode(servo_id, Mode::Position).await {
                    log::warn!("set position mode failed for servo {servo_id}: {:?}", err);
                    continue;
                }
                wheel_modes.mark_servo_not_ready(servo_id);
                if let Err(err) = servo.write_angle(servo_id, angle_deg, speed, acc).await {
                    log::warn!(
                        "direct servo command failed for servo {servo_id}: {:?}",
                        err
                    );
                }
            }
        }
    }
}

#[embassy_executor::task]
pub async fn arm_task(
    mut servo: ServoController,
    intents: &'static IntentChannel,
    telemetry: &'static TelemetryChannel,
) {
    let mut controller = ArmController::new(Instant::now().as_millis());
    let mut wheel_modes = WheelModeState::new(&controller);
    let mut telemetry_seq = 0;
    let mut last_telemetry_ms = 0;
    initialize_wheel_mode(&mut servo, &controller, &mut wheel_modes).await;

    loop {
        let now = Instant::now().as_millis();
        drain_intents(intents, &mut controller, &mut servo, &mut wheel_modes, now).await;
        read_feedback(&mut servo, &mut controller, &mut wheel_modes, now).await;
        apply_outputs(&mut servo, &mut controller, &mut wheel_modes, now).await;
        publish_telemetry(
            telemetry,
            &controller,
            &mut telemetry_seq,
            &mut last_telemetry_ms,
            now,
        );
        Timer::after(CONTROL_PERIOD).await;
    }
}
