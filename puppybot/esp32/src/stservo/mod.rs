pub use puppybot_core::stservo::*;

#[cfg(feature = "esp32")]
mod esp32;
#[cfg(feature = "esp32")]
pub use esp32::EspUartBus;
