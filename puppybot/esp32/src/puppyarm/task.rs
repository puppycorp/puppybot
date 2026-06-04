#[cfg(feature = "esp32")]
use embassy_time::{Duration, Instant, Timer};
#[cfg(feature = "esp32")]
use esp_hal::Blocking;

use super::controller::ArmCommand;
pub use super::puppyarm::PuppyArm;
#[cfg(feature = "esp32")]
pub use super::puppyarm::{IntentChannel, PuppyarmTelemetry, TelemetryChannel};
#[cfg(feature = "esp32")]
use crate::stservo::EspUartBus;
use crate::stservo::{Mode, SerialBus, StServo};

#[cfg(feature = "esp32")]
const CONTROL_PERIOD: Duration = Duration::from_millis(20);
const ARM_WHEEL_ACC: u8 = 0;

#[cfg(feature = "esp32")]
pub type ServoController = StServo<EspUartBus<Blocking>>;

pub trait ArmCommandSource {
    fn try_receive_arm_cmd(&mut self) -> Option<ArmCommand>;
}

#[cfg(feature = "esp32")]
impl ArmCommandSource for &'static IntentChannel {
    fn try_receive_arm_cmd(&mut self) -> Option<ArmCommand> {
        self.try_receive().ok()
    }
}

pub struct ArmWorker {
    arm: PuppyArm,
}

impl ArmWorker {
    pub fn new(now: u64) -> Self {
        Self {
            arm: PuppyArm::new(now),
        }
    }

    pub fn arm(&self) -> &PuppyArm {
        &self.arm
    }

    pub fn arm_mut(&mut self) -> &mut PuppyArm {
        &mut self.arm
    }

    pub async fn run_once<B, C>(&mut self, servo: &mut StServo<B>, commands: &mut C, now: u64)
    where
        B: SerialBus,
        B::Error: core::fmt::Debug,
        C: ArmCommandSource,
    {
        while let Some(command) = commands.try_receive_arm_cmd() {
            self.arm.handle_arm_cmd(command, now);
        }

        for request in self.arm.feedback_requests() {
            match servo.read_position(request.servo_id).await {
                Ok(tick) => self.arm.record_feedback(request.joint, tick, now),
                Err(err) => {
                    log::warn!(
                        "read position failed for servo {}: {:?}",
                        request.servo_id,
                        err
                    );
                    self.arm.record_feedback_error(request.joint);
                }
            }
        }

        let initialize_wheel_mode = self.arm.take_initialize_wheel_mode();
        let outputs = self.arm.update(now);
        for joint in 0..outputs.len() {
            let output = outputs[joint];
            if !initialize_wheel_mode && !output.should_send {
                continue;
            }

            let mut wheel_mode_ready = self.arm.wheel_mode_ready(joint, output.servo_id);
            if !wheel_mode_ready {
                let force_wheel_mode = initialize_wheel_mode || output.speed == 0;
                if !self
                    .arm
                    .begin_wheel_mode_attempt(joint, output.servo_id, now, force_wheel_mode)
                {
                    continue;
                }

                let result = servo.set_mode(output.servo_id, Mode::Wheel).await;
                wheel_mode_ready = result.is_ok();
                if wheel_mode_ready {
                    log::info!("mode {:?} ready for servo {}", Mode::Wheel, output.servo_id);
                } else if let Err(err) = result {
                    log::warn!(
                        "set mode {:?} failed for servo {}: {:?}",
                        Mode::Wheel,
                        output.servo_id,
                        err
                    );
                }
                self.arm.record_set_mode_result(
                    joint,
                    output.servo_id,
                    Mode::Wheel,
                    wheel_mode_ready,
                );
            }

            if !wheel_mode_ready || !self.arm.can_write_wheel_speed(joint, output.servo_id) {
                continue;
            }

            let result = servo
                .write_wheel_speed(output.servo_id, output.speed, ARM_WHEEL_ACC)
                .await;
            let success = result.is_ok();
            if let Err(err) = result {
                log::warn!(
                    "set wheel speed failed for servo {} speed {}: {:?}",
                    output.servo_id,
                    output.speed,
                    err
                );
            }
            self.arm
                .record_wheel_speed_result(joint, output.servo_id, output.speed, success, now);
        }
    }

    #[cfg(feature = "esp32")]
    pub fn publish_telemetry(&mut self, telemetry: &'static TelemetryChannel, now: u64) {
        self.arm.publish_telemetry(telemetry, now);
    }
}

#[cfg(feature = "esp32")]
#[embassy_executor::task]
pub async fn arm_task(
    mut servo: ServoController,
    intents: &'static IntentChannel,
    telemetry: &'static TelemetryChannel,
) {
    let mut worker = ArmWorker::new(Instant::now().as_millis());
    let mut commands = intents;

    loop {
        let now = Instant::now().as_millis();
        worker.run_once(&mut servo, &mut commands, now).await;
        worker.publish_telemetry(telemetry, now);
        Timer::after(CONTROL_PERIOD).await;
    }
}
