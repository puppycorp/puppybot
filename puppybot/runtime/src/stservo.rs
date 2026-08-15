use std::{
    fs,
    io::{self, ErrorKind, Read, Write},
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

use embassy_time::Duration as EmbassyDuration;
use puppybot_core::stservo::{DEFAULT_BAUD, SerialBus, StServo, build_packet};

const STSERVO_PORT_ENV: &str = "PUPPYBOT_STSERVO_PORT";
const STSERVO_BAUD_ENV: &str = "PUPPYBOT_STSERVO_BAUD";
const STSERVO_PROBE_ENV: &str = "PUPPYBOT_STSERVO_PROBE";
const DEFAULT_READ_TIMEOUT: Duration = Duration::from_millis(1);
const AUTO_DETECT_PROBE_TIMEOUT: Duration = Duration::from_millis(50);
const VIRTUAL_BUS_TRANSACTION_TIMEOUT_MS: u64 = 500;
const STSERVO_PING_INSTRUCTION: u8 = 0x01;
const SERIAL_CACHE_FILE: &str = "puppybot-runtime-stservo-port";
const SUPPORTED_PORT_PATTERNS: &[&str] = &[
    "/dev/serial/by-id/",
    "/dev/ttyACM",
    "/dev/ttyUSB",
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

fn auto_detect_ports() -> Vec<String> {
    let mut ports = list_supported_ports();
    ports.sort();
    ports.dedup();

    if let Some(port) = read_cached_port() {
        ports.retain(|candidate| candidate != &port);
        ports.insert(0, port);
    }
    ports
}

impl RuntimeSerialConfig {
    fn from_port(port: &str) -> Option<Self> {
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

fn contains_ping_response(bytes: &[u8], servo_id: u8) -> bool {
    bytes.windows(6).any(|frame| {
        frame[0] == 0xff
            && frame[1] == 0xff
            && frame[2] == servo_id
            && frame[3] == 2
            && frame[4] == 0
            && frame[5]
                == !frame[2..5]
                    .iter()
                    .fold(0u8, |sum, byte| sum.wrapping_add(*byte))
    })
}

fn probe_servo_id(bus: &mut RuntimeSerialBus, servo_id: u8) -> bool {
    let _ = bus.port.clear(serialport::ClearBuffer::Input);

    let mut request = [0u8; 6];
    let Ok(request_len) = build_packet(&mut request, servo_id, STSERVO_PING_INSTRUCTION, &[])
    else {
        return false;
    };
    if bus.write_all(&request[..request_len]).is_err() {
        return false;
    }

    let deadline = Instant::now() + AUTO_DETECT_PROBE_TIMEOUT;
    let mut response = [0u8; 64];
    let mut response_len = 0;
    while Instant::now() < deadline && response_len < response.len() {
        match bus.read_buffered(&mut response[response_len..]) {
            Ok(0) => {}
            Ok(read) => {
                response_len += read;
                if contains_ping_response(&response[..response_len], servo_id) {
                    return true;
                }
            }
            Err(_) => return false,
        }
    }
    false
}

fn probe_configured_servos(bus: &mut RuntimeSerialBus, servo_ids: &[u8]) -> Option<u8> {
    servo_ids
        .iter()
        .copied()
        .find(|servo_id| probe_servo_id(bus, *servo_id))
}

fn runtime_stservo_for_config(
    bus: RuntimeSerialBus,
    config: &RuntimeSerialConfig,
) -> RuntimeStServo {
    let servo = StServo::new(bus);
    if is_ephemeral_virtual_port(&config.port) {
        log::info!(
            "runtime using {} ms STServo transaction timeout for virtual serial bus {}",
            VIRTUAL_BUS_TRANSACTION_TIMEOUT_MS,
            config.port
        );
        servo.with_timeout(EmbassyDuration::from_millis(
            VIRTUAL_BUS_TRANSACTION_TIMEOUT_MS,
        ))
    } else {
        servo
    }
}

fn open_config(config: &RuntimeSerialConfig) -> Option<RuntimeStServo> {
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
                return Some(runtime_stservo_for_config(bus, &config));
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
            Some(runtime_stservo_for_config(bus, &config))
        }
        Err(err) => {
            log::warn!("runtime STServo serial bus open failed: {err}");
            None
        }
    }
}

fn auto_detect_serial(servo_ids: &[u8]) -> Option<RuntimeStServo> {
    let ports = auto_detect_ports();
    if ports.is_empty() {
        log::info!("runtime found no supported USB serial devices to probe for STServo");
        return None;
    }

    let mut matches = Vec::new();
    for port in ports {
        let Some(config) = RuntimeSerialConfig::from_port(&port) else {
            continue;
        };
        let Ok(mut bus) = RuntimeSerialBus::open(&config) else {
            log::info!("runtime could not open STServo candidate {port}");
            continue;
        };
        match probe_configured_servos(&mut bus, servo_ids) {
            Some(servo_id) => {
                log::info!("runtime detected STServo {servo_id} on serial port {port}");
                matches.push((config, bus));
            }
            None => log::info!("runtime found no configured STServo replies on {port}"),
        }
    }

    match matches.as_mut_slice() {
        [(config, _)] => {
            remember_port(&config.port);
        }
        [] => return None,
        _ => {
            log::warn!(
                "multiple STServo buses detected; set {STSERVO_PORT_ENV}: {}",
                matches
                    .iter()
                    .map(|(config, _)| config.port.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            );
            return None;
        }
    }

    let (config, bus) = matches.pop().expect("one detected STServo bus");
    Some(runtime_stservo_for_config(bus, &config))
}

pub(crate) fn open_serial(port: Option<&str>, servo_ids: &[u8]) -> Option<RuntimeStServo> {
    let explicit_port = port
        .map(str::to_string)
        .or_else(|| std::env::var(STSERVO_PORT_ENV).ok());
    if let Some(port) = explicit_port {
        let Some(config) = RuntimeSerialConfig::from_port(&port) else {
            log::warn!("configured STServo serial port is empty");
            return None;
        };
        return open_config(&config);
    }

    auto_detect_serial(servo_ids)
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
            RuntimeSerialConfig::from_port(" /dev/ttyUSB0 ").map(|config| config.port),
            Some("/dev/ttyUSB0".to_string())
        );
    }

    #[test]
    fn serial_config_rejects_empty_explicit_port() {
        assert_eq!(RuntimeSerialConfig::from_port("  "), None);
    }

    #[test]
    fn supported_port_name_accepts_known_usb_serial_paths() {
        assert!(is_supported_port_name(
            "/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0"
        ));
        assert!(is_supported_port_name("/dev/ttyACM0"));
        assert!(is_supported_port_name("/dev/ttyUSB0"));
        assert!(is_supported_port_name("/dev/cu.usbmodem5A7C1186261"));
        assert!(is_supported_port_name("/dev/cu.wchusbserial1420"));
    }

    #[test]
    fn supported_port_name_rejects_unrelated_ports() {
        assert!(!is_supported_port_name("/dev/cu.Bluetooth-Incoming-Port"));
        assert!(!is_supported_port_name("COM1"));
    }

    #[test]
    fn ping_response_requires_valid_stservo_status_packet() {
        assert!(contains_ping_response(&[0xff, 0xff, 1, 2, 0, 0xfc], 1));
        assert!(!contains_ping_response(&[0xff, 0xff, 1, 2, 0, 0], 1));
        assert!(!contains_ping_response(&[0xff, 0xff, 2, 2, 0, 0xfb], 1));
        assert!(!contains_ping_response(&[0xff, 0xff, 1, 2, 1, 0xfb], 1));
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
