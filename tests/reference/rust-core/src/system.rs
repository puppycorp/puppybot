use crate::{
    drive::{DriveActuator, NoopDriveActuator},
    protocol::ProtocolEvent,
    puppyarm::types::ControllerError,
    robot::Puppybot,
    stservo::{SerialBus, StServo},
};

pub(crate) const PUPPYBOT_SYSTEM_TICK_MS: u64 = 20;

pub struct PuppyBotSystem<B, D = NoopDriveActuator> {
    robot: Puppybot,
    servo: StServo<B>,
    drive_actuator: D,
    now_ms: u64,
}

impl<B> PuppyBotSystem<B> {
    pub fn with_servo(robot: Puppybot, servo: StServo<B>) -> Self {
        Self {
            robot,
            servo,
            drive_actuator: NoopDriveActuator,
            now_ms: 0,
        }
    }
}

impl<B, D> PuppyBotSystem<B, D> {
    pub fn with_servo_and_drive(robot: Puppybot, servo: StServo<B>, drive_actuator: D) -> Self {
        Self {
            robot,
            servo,
            drive_actuator,
            now_ms: 0,
        }
    }

    pub fn robot(&self) -> &Puppybot {
        &self.robot
    }

    pub fn robot_mut(&mut self) -> &mut Puppybot {
        &mut self.robot
    }

    pub fn servo(&self) -> &StServo<B> {
        &self.servo
    }

    pub fn servo_mut(&mut self) -> &mut StServo<B> {
        &mut self.servo
    }

    pub fn drive_actuator(&self) -> &D {
        &self.drive_actuator
    }

    pub fn drive_actuator_mut(&mut self) -> &mut D {
        &mut self.drive_actuator
    }

    pub fn now_ms(&self) -> u64 {
        self.now_ms
    }

    pub fn set_now_ms(&mut self, now_ms: u64) {
        self.now_ms = now_ms;
    }
}

impl<B> PuppyBotSystem<B, NoopDriveActuator>
where
    B: SerialBus,
{
    pub fn new(robot: Puppybot, bus: B) -> Self {
        Self::with_servo(robot, StServo::new(bus))
    }
}

impl<B, D> PuppyBotSystem<B, D>
where
    B: SerialBus,
    B::Error: core::fmt::Debug,
    D: DriveActuator,
    D::Error: core::fmt::Debug,
{
    pub async fn run_once_at<F>(&mut self, now_ms: u64, receive_event: F)
    where
        F: FnMut() -> Option<ProtocolEvent>,
    {
        self.now_ms = now_ms;
        self.robot
            .run_once_with_drive(
                &mut self.servo,
                &mut self.drive_actuator,
                self.now_ms,
                receive_event,
            )
            .await;
    }

    pub async fn try_run_once_at<F>(
        &mut self,
        now_ms: u64,
        receive_event: F,
    ) -> Result<(), ControllerError>
    where
        F: FnMut() -> Option<ProtocolEvent>,
    {
        self.now_ms = now_ms;
        self.robot
            .try_run_once_with_drive(
                &mut self.servo,
                &mut self.drive_actuator,
                self.now_ms,
                receive_event,
            )
            .await
    }

    pub async fn run_once<F>(&mut self, receive_event: F)
    where
        F: FnMut() -> Option<ProtocolEvent>,
    {
        self.robot
            .run_once_with_drive(
                &mut self.servo,
                &mut self.drive_actuator,
                self.now_ms,
                receive_event,
            )
            .await;
        self.now_ms = self.now_ms.wrapping_add(PUPPYBOT_SYSTEM_TICK_MS);
    }
}
