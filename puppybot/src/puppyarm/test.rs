use super::{
    controller::ArmCommand,
    task::{ArmCommandSource, ArmWorker},
};
use crate::stservo::{
    Mode, StServo,
    mock::{FakeSerialBus, block_on_ready},
};

struct TestCommands {
    commands: [Option<ArmCommand>; 4],
    index: usize,
}

impl TestCommands {
    fn new(commands: &[ArmCommand]) -> Self {
        let mut out = [None; 4];
        for (index, command) in commands.iter().copied().enumerate() {
            out[index] = Some(command);
        }
        Self {
            commands: out,
            index: 0,
        }
    }
}

impl ArmCommandSource for TestCommands {
    fn try_receive_arm_cmd(&mut self) -> Option<ArmCommand> {
        let command = self.commands.get_mut(self.index)?.take();
        self.index += 1;
        command
    }
}

#[test]
fn arm_worker_runs_arm_commands_over_fake_serial_bus() {
    let mut servo = StServo::new(
        FakeSerialBus::new()
            .with_servo(1, 0)
            .with_servo(2, 550)
            .with_servo(3, 2900)
            .with_servo(4, 1800),
    );
    let mut worker = ArmWorker::new(0);
    let mut commands = TestCommands::new(&[
        ArmCommand::SetSpeed(300),
        ArmCommand::Spin {
            joint: 0,
            direction: 1,
        },
    ]);

    block_on_ready(worker.run_once(&mut servo, &mut commands, 20));

    let yaw = servo.bus().servo(1).unwrap();
    assert_eq!(yaw.mode, Mode::Wheel);
    assert_eq!(yaw.wheel_speed, 300);
}
