use std::{
    io::{self, ErrorKind, Read, Write},
    time::Duration,
};

use puppybot_core::stservo::{DEFAULT_BAUD, SerialBus, StServo};

const STSERVO_PORT_ENV: &str = "PUPPYBOT_STSERVO_PORT";
const STSERVO_BAUD_ENV: &str = "PUPPYBOT_STSERVO_BAUD";
const STSERVO_PROBE_ENV: &str = "PUPPYBOT_STSERVO_PROBE";
const DEFAULT_READ_TIMEOUT: Duration = Duration::from_millis(1);

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct RuntimeSerialConfig {
    pub port: String,
    pub baud: u32,
}

pub(crate) struct RuntimeSerialBus {
    port: Box<dyn serialport::SerialPort>,
}

pub(crate) type RuntimeStServo = StServo<RuntimeSerialBus>;

fn parse_baud(value: &str) -> Option<u32> {
    value.trim().parse::<u32>().ok().filter(|baud| *baud > 0)
}

fn is_nonblocking_empty(err: &io::Error) -> bool {
    matches!(
        err.kind(),
        ErrorKind::WouldBlock | ErrorKind::TimedOut | ErrorKind::Interrupted
    )
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

pub(crate) fn open_serial_from_env() -> Option<RuntimeStServo> {
    let Some(config) = RuntimeSerialConfig::from_env() else {
        log::info!(
            "runtime using simulated PuppyArm state; set {STSERVO_PORT_ENV} to use hardware"
        );
        return None;
    };

    log::info!(
        "runtime STServo serial bus configured on {} at {} baud",
        config.port,
        config.baud
    );

    if std::env::var(STSERVO_PROBE_ENV).ok().as_deref() == Some("1") {
        match RuntimeSerialBus::open(&config) {
            Ok(bus) => {
                log::info!("runtime STServo serial bus probe opened successfully");
                return Some(StServo::new(bus));
            }
            Err(err) => {
                log::warn!("runtime STServo serial bus probe failed: {err}");
                return None;
            }
        }
    }

    match RuntimeSerialBus::open(&config) {
        Ok(bus) => Some(StServo::new(bus)),
        Err(err) => {
            log::warn!("runtime STServo serial bus open failed: {err}");
            None
        }
    }
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
