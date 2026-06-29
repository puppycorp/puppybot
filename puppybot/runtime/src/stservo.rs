use std::{
    fs,
    io::{self, ErrorKind, Read, Write},
    path::{Path, PathBuf},
    time::Duration,
};

use puppybot_core::stservo::{DEFAULT_BAUD, SerialBus, StServo};

const STSERVO_PORT_ENV: &str = "PUPPYBOT_STSERVO_PORT";
const STSERVO_BAUD_ENV: &str = "PUPPYBOT_STSERVO_BAUD";
const STSERVO_PROBE_ENV: &str = "PUPPYBOT_STSERVO_PROBE";
const DEFAULT_READ_TIMEOUT: Duration = Duration::from_millis(1);
const SERIAL_CACHE_FILE: &str = "puppybot-runtime-stservo-port";
const SUPPORTED_PORT_PATTERNS: &[&str] = &[
    "/dev/serial/by-id/",
    "/dev/cu.usbmodem",
    "/dev/cu.usbserial",
    "/dev/cu.wchusbserial",
    "/dev/cu.SLAB_USBtoUART",
    "FTDI",
    "CP210",
    "CP2102",
    "Silicon_Labs",
    "CH340",
    "CH341",
    "QinHeng",
    "USB_Serial",
    "USB2.0-Serial",
];

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

fn default_baud() -> u32 {
    std::env::var(STSERVO_BAUD_ENV)
        .ok()
        .and_then(|value| parse_baud(&value))
        .unwrap_or(DEFAULT_BAUD)
}

fn is_supported_port_name(port: &str) -> bool {
    SUPPORTED_PORT_PATTERNS
        .iter()
        .any(|pattern| port.contains(pattern))
}

fn is_ephemeral_virtual_port(port: &str) -> bool {
    port.starts_with("/dev/pts/")
}

fn is_cacheable_port(port: &str) -> bool {
    !is_ephemeral_virtual_port(port)
}

fn serial_cache_path() -> Option<PathBuf> {
    std::env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .or_else(|| {
            std::env::var_os("HOME")
                .map(PathBuf::from)
                .map(|home| home.join(".cache"))
        })
        .map(|cache| cache.join(SERIAL_CACHE_FILE))
}

fn read_cached_port() -> Option<String> {
    let path = serial_cache_path()?;
    let port = fs::read_to_string(path).ok()?;
    let port = port.trim();
    if port.is_empty() || !Path::new(port).exists() {
        return None;
    }
    if !is_cacheable_port(port) {
        log::info!(
            "runtime ignoring remembered ephemeral STServo serial port {port}; pass --servo-device with the current virtual bus path"
        );
        return None;
    }
    Some(port.to_string())
}

fn remember_port(port: &str) {
    if !is_cacheable_port(port) {
        log::info!("runtime not remembering ephemeral STServo serial port {port}");
        return;
    }
    let Some(path) = serial_cache_path() else {
        return;
    };
    if let Some(parent) = path.parent() {
        if let Err(err) = fs::create_dir_all(parent) {
            log::warn!("failed to create serial cache directory: {err}");
            return;
        }
    }
    if let Err(err) = fs::write(path, port) {
        log::warn!("failed to remember STServo serial port {port}: {err}");
    }
}

fn list_supported_ports() -> Vec<String> {
    match serialport::available_ports() {
        Ok(ports) => ports
            .into_iter()
            .map(|port| port.port_name)
            .filter(|port| is_supported_port_name(port))
            .collect(),
        Err(err) => {
            log::warn!("failed to list serial ports for STServo auto-detection: {err}");
            Vec::new()
        }
    }
}

fn auto_detect_port() -> Option<String> {
    if let Some(port) = read_cached_port() {
        log::info!("runtime reusing remembered STServo serial port {port}");
        return Some(port);
    }

    let ports = list_supported_ports();
    match ports.as_slice() {
        [port] => {
            log::info!("runtime auto-detected STServo serial port {port}");
            Some(port.clone())
        }
        [] => None,
        _ => {
            log::warn!(
                "multiple supported STServo serial ports found; set {STSERVO_PORT_ENV}: {}",
                ports.join(", ")
            );
            None
        }
    }
}

impl RuntimeSerialConfig {
    pub(crate) fn from_port_or_env_or_auto_detect(port: Option<&str>) -> Option<Self> {
        let port = match port {
            Some(port) => port.to_string(),
            None => match std::env::var(STSERVO_PORT_ENV).ok() {
                Some(port) => port,
                None => auto_detect_port()?,
            },
        };
        let port = port.trim();
        if port.is_empty() {
            return None;
        }

        Some(Self {
            port: port.to_string(),
            baud: default_baud(),
        })
    }
}

impl RuntimeSerialBus {
    pub(crate) fn open(config: &RuntimeSerialConfig) -> serialport::Result<Self> {
        let mut builder = serialport::new(&config.port, config.baud)
            .timeout(DEFAULT_READ_TIMEOUT)
            .data_bits(serialport::DataBits::Eight)
            .flow_control(serialport::FlowControl::None)
            .parity(serialport::Parity::None)
            .stop_bits(serialport::StopBits::One);

        if is_ephemeral_virtual_port(&config.port) {
            log::info!(
                "runtime opening ephemeral STServo serial port {} without exclusive lock",
                config.port
            );
            builder = builder.exclusive(false);
        }

        let port = builder.open()?;
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

pub(crate) fn open_serial(port: Option<&str>) -> Option<RuntimeStServo> {
    let Some(config) = RuntimeSerialConfig::from_port_or_env_or_auto_detect(port) else {
        log::info!(
            "runtime using simulated PuppyArm state; set {STSERVO_PORT_ENV} or pass --servo-device to use hardware"
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
                remember_port(&config.port);
                return Some(StServo::new(bus));
            }
            Err(err) => {
                log::warn!("runtime STServo serial bus probe failed: {err}");
                return None;
            }
        }
    }

    match RuntimeSerialBus::open(&config) {
        Ok(bus) => {
            remember_port(&config.port);
            Some(StServo::new(bus))
        }
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

    #[test]
    fn serial_config_accepts_explicit_port() {
        assert_eq!(
            RuntimeSerialConfig::from_port_or_env_or_auto_detect(Some(" /dev/ttyUSB0 "))
                .map(|config| config.port),
            Some("/dev/ttyUSB0".to_string())
        );
    }

    #[test]
    fn serial_config_rejects_empty_explicit_port() {
        assert_eq!(
            RuntimeSerialConfig::from_port_or_env_or_auto_detect(Some("  ")),
            None
        );
    }

    #[test]
    fn supported_port_name_accepts_known_usb_serial_paths() {
        assert!(is_supported_port_name(
            "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0"
        ));
        assert!(is_supported_port_name("/dev/cu.usbmodem5A7C1186261"));
        assert!(is_supported_port_name("/dev/cu.wchusbserial1420"));
    }

    #[test]
    fn supported_port_name_rejects_unrelated_ports() {
        assert!(!is_supported_port_name("/dev/cu.Bluetooth-Incoming-Port"));
        assert!(!is_supported_port_name("COM1"));
    }

    #[test]
    fn cacheable_port_rejects_ephemeral_virtual_ports() {
        assert!(!is_cacheable_port("/dev/pts/9"));
        assert!(!is_cacheable_port("/dev/pts/123"));
    }

    #[test]
    fn cacheable_port_accepts_stable_serial_ports() {
        assert!(is_cacheable_port("/dev/ttyUSB0"));
        assert!(is_cacheable_port(
            "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0"
        ));
        assert!(is_cacheable_port("/dev/cu.usbserial1420"));
    }
}
