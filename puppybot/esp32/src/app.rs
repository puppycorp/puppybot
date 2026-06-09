#![cfg(feature = "esp32")]

extern crate alloc;

use embassy_time::Instant;

use crate::{
    protocol::{self, ProtocolEvent, ProtocolOutput, ProtocolState},
    puppyarm::task::{IntentChannel, PuppyarmTelemetry},
};
use puppybot_core::robot;

pub struct PuppybotApp {
    protocol: ProtocolState,
}

impl PuppybotApp {
    pub fn new(now_ms: u64) -> Self {
        let _ = now_ms;
        Self {
            protocol: ProtocolState::default(),
        }
    }

    pub fn handle_frame(
        &mut self,
        frame: &[u8],
        telemetry_enabled: &mut bool,
        arm_intents: &'static IntentChannel,
    ) -> ProtocolOutput {
        self.protocol.telemetry_enabled = *telemetry_enabled;
        let output = protocol::handle_binary_command(frame, &mut self.protocol);
        *telemetry_enabled = self.protocol.telemetry_enabled;

        let now_ms = Instant::now().as_millis();
        for event in output.events.iter().copied() {
            self.handle_event(event, arm_intents, now_ms);
        }

        output
    }

    pub fn tick(&mut self) {}

    fn handle_event(
        &mut self,
        event: ProtocolEvent,
        arm_intents: &'static IntentChannel,
        now_ms: u64,
    ) {
        let _ = now_ms;
        if arm_intents.try_send(event).is_err() {
            log::warn!("robot intent queue full; dropping intent: {:?}", event);
        }
    }
}

pub fn arm_state_frame(telemetry: &PuppyarmTelemetry) -> alloc::vec::Vec<u8> {
    robot::arm_state_frame(telemetry)
}
