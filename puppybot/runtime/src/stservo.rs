use std::{
    io::{self, ErrorKind, Read, Write},
    time::Duration,
};

use puppybot_core::stservo::{DEFAULT_BAUD, SerialBus};

const STSERVO_PORT_ENV: &str = "PUPPYBOT_STSERVO_PORT";
const STSERVO_BAUD_ENV: &str = "PUPPYBOT_STSERVO_BAUD";
const STSERVO_PROBE_ENV: &str = "PUPPYBOT_STSERVO_PROBE";
const DEFAULT_READ_TIMEOUT: Duration = Duration::from_millis(1);

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct RuntimeSerialConfig {
    pub port: String,
    pub baud: u32,
}

impl RuntimeSerialConfig {
    pub(crate) fn from_env() -> Option<Self> {
        let port = std::env::var(STSERVO_PORT_ENV).ok()?;
        let port = port.trim();
        if port.is_empty() {
            return None;
        }

        Some(Self {
            port: port.to_string(),
            baud: std::env::var(STSERVO_BAUD_ENV)
                .ok()
                .and_then(|value| parse_baud(&value))
                .unwrap_or(DEFAULT_BAUD),
        })
    }
}

pub(crate) struct RuntimeSerialBus {
    port: Box<dyn serialport::SerialPort>,
}

impl RuntimeSerialBus {
    pub(crate) fn open(config: &RuntimeSerialConfig) -> serialport::Result<Self> {
        let port = serialport::new(&config.port, config.baud)
            .timeout(DEFAULT_READ_TIMEOUT)
            .data_bits(serialport::DataBits::Eight)
            .flow_control(serialport::FlowControl::None)
            .parity(serialport::Parity::None)
            .stop_bits(serialport::StopBits::One)
            .open()?;
        Ok(Self { port })
    }
}

impl SerialBus for RuntimeSerialBus {
    type Error = io::Error;

    fn write(&mut self, bytes: &[u8]) -> Result<usize, Self::Error> {
        self.port.write(bytes)
    }

    fn flush(&mut self) -> Result<(), Self::Error> {
        self.port.flush()
    }

    fn read_buffered(&mut self, bytes: &mut [u8]) -> Result<usize, Self::Error> {
        match self.port.read(bytes) {
            Ok(read) => Ok(read),
            Err(err) if is_nonblocking_empty(&err) => Ok(0),
            Err(err) => Err(err),
        }
    }
}

pub(crate) fn log_serial_config_from_env() {
    let Some(config) = RuntimeSerialConfig::from_env() else {
        return;
    };

    log::info!(
        "runtime STServo serial bus configured on {} at {} baud",
        config.port,
        config.baud
    );
    log::info!(
        "runtime currently uses simulated PuppyArm state; serial bus is available for the hardware arm worker"
    );

    if std::env::var(STSERVO_PROBE_ENV).ok().as_deref() == Some("1") {
        match RuntimeSerialBus::open(&config) {
            Ok(_) => log::info!("runtime STServo serial bus probe opened successfully"),
            Err(err) => log::warn!("runtime STServo serial bus probe failed: {err}"),
        }
    }
}

fn is_nonblocking_empty(err: &io::Error) -> bool {
    matches!(
        err.kind(),
        ErrorKind::WouldBlock | ErrorKind::TimedOut | ErrorKind::Interrupted
    )
}

fn parse_baud(value: &str) -> Option<u32> {
    value.trim().parse::<u32>().ok().filter(|baud| *baud > 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_baud_rejects_empty_zero_and_invalid_values() {
        assert_eq!(parse_baud(""), None);
        assert_eq!(parse_baud("0"), None);
        assert_eq!(parse_baud("wat"), None);
    }

    #[test]
    fn parse_baud_accepts_positive_values() {
        assert_eq!(parse_baud("1000000"), Some(1_000_000));
        assert_eq!(parse_baud(" 115200 "), Some(115_200));
    }
}
