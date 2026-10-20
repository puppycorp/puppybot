#[cfg(feature = "esp32")]
use embassy_time::{Duration, Instant, Timer};
#[cfg(feature = "esp32")]
use esp_hal::Blocking;

#[cfg(feature = "esp32")]
use embassy_sync::{blocking_mutex::raw::CriticalSectionRawMutex, channel::Channel};

#[cfg(feature = "esp32")]
use crate::config::runtime_config;
#[cfg(feature = "esp32")]
use crate::stservo::EspUartBus;
use crate::stservo::StServo;
use puppybot_core::{protocol::ProtocolEvent, robot::Puppybot};

pub use puppybot_core::puppyarm::puppyarm::PuppyarmTelemetry;

#[cfg(feature = "esp32")]
const CONTROL_PERIOD: Duration = Duration::from_millis(20);
#[cfg(feature = "esp32")]
const TELEMETRY_PERIOD_MS: u64 = 100;

#[cfg(feature = "esp32")]
pub type ServoController = StServo<EspUartBus<Blocking>>;
#[cfg(feature = "esp32")]
pub type IntentChannel = Channel<CriticalSectionRawMutex, ProtocolEvent, 16>;
#[cfg(feature = "esp32")]
pub type TelemetryChannel = Channel<CriticalSectionRawMutex, PuppyarmTelemetry, 4>;

#[cfg(feature = "esp32")]
fn publish_telemetry(telemetry: &'static TelemetryChannel, snapshot: PuppyarmTelemetry) {
    if telemetry.try_send(snapshot).is_err() {
        let _ = telemetry.try_receive();
        let _ = telemetry.try_send(snapshot);
    }
}

#[cfg(feature = "esp32")]
#[embassy_executor::task]
pub async fn robot_task(
    mut servo: ServoController,
    intents: &'static IntentChannel,
    telemetry: &'static TelemetryChannel,
) {
    let config = runtime_config();
    let mut robot = Puppybot::new_with_config(&config, Instant::now().as_millis())
        .expect("embedded runtime configuration must be valid");
    let mut last_telemetry_ms = 0;

    loop {
        let now = Instant::now().as_millis();
        robot
            .run_once(&mut servo, now, || intents.try_receive().ok())
            .await;

        if now.saturating_sub(last_telemetry_ms) >= TELEMETRY_PERIOD_MS {
            last_telemetry_ms = now;
            publish_telemetry(telemetry, robot.arm_telemetry());
        }

        Timer::after(CONTROL_PERIOD).await;
    }
}
