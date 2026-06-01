use core::cmp;

use embassy_time::{Duration, Instant, Timer};

pub const DEFAULT_BAUD: u32 = 1_000_000;
pub const MIN_SERVO_ID: u8 = 0;
pub const MAX_SERVO_ID: u8 = 253;
pub const MAX_POSITION: u16 = 4095;

const HEADER: [u8; 2] = [0xff, 0xff];
const BROADCAST_ID: u8 = 0xfe;
const MAX_PACKET_LEN: usize = 250;
const MAX_PARAMS: usize = 64;

const INST_PING: u8 = 0x01;
const INST_READ: u8 = 0x02;
const INST_WRITE: u8 = 0x03;

const SMS_STS_ID: u8 = 5;
const SMS_STS_MODE: u8 = 33;
const SMS_STS_ACC: u8 = 41;
const SMS_STS_LOCK: u8 = 55;
const SMS_STS_PRESENT_POSITION_L: u8 = 56;
const SMS_STS_PRESENT_VOLTAGE: u8 = 62;
const SMS_STS_PRESENT_TEMPERATURE: u8 = 63;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error<E> {
    InvalidId,
    InvalidPacket,
    PacketTooLarge,
    Timeout,
    Checksum,
    UnexpectedId,
    Status(u8),
    Io(E),
}

impl<E> Error<E> {
    fn with_error<T>(self) -> Error<T> {
        match self {
            Self::InvalidId => Error::InvalidId,
            Self::InvalidPacket => Error::InvalidPacket,
            Self::PacketTooLarge => Error::PacketTooLarge,
            Self::Timeout => Error::Timeout,
            Self::Checksum => Error::Checksum,
            Self::UnexpectedId => Error::UnexpectedId,
            Self::Status(status) => Error::Status(status),
            Self::Io(_) => unreachable!(),
        }
    }
}

pub trait SerialBus {
    type Error;

    fn write(&mut self, bytes: &[u8]) -> Result<usize, Self::Error>;
    fn flush(&mut self) -> Result<(), Self::Error>;
    fn read_buffered(&mut self, bytes: &mut [u8]) -> Result<usize, Self::Error>;

    fn write_all(&mut self, mut bytes: &[u8]) -> Result<(), Self::Error> {
        while !bytes.is_empty() {
            let written = self.write(bytes)?;
            if written == 0 {
                continue;
            }
            bytes = &bytes[written..];
        }
        self.flush()
    }
}

impl<Dm> SerialBus for esp_hal::uart::Uart<'_, Dm>
where
    Dm: esp_hal::DriverMode,
{
    type Error = esp_hal::uart::IoError;

    fn write(&mut self, bytes: &[u8]) -> Result<usize, Self::Error> {
        self.write(bytes).map_err(esp_hal::uart::IoError::Tx)
    }

    fn flush(&mut self) -> Result<(), Self::Error> {
        self.flush().map_err(esp_hal::uart::IoError::Tx)
    }

    fn read_buffered(&mut self, bytes: &mut [u8]) -> Result<usize, Self::Error> {
        self.read_buffered(bytes)
            .map_err(esp_hal::uart::IoError::Rx)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Position,
    Wheel,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Status {
    pub voltage_raw: u8,
    pub temperature_c: u8,
}

#[derive(Clone, Copy, Debug)]
pub struct StServo<B> {
    bus: B,
    timeout: Duration,
}

impl<B> StServo<B>
where
    B: SerialBus,
{
    pub fn new(bus: B) -> Self {
        Self {
            bus,
            timeout: Duration::from_millis(50),
        }
    }

    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    pub fn bus_mut(&mut self) -> &mut B {
        &mut self.bus
    }

    pub async fn ping(&mut self, servo_id: u8) -> Result<(), Error<B::Error>> {
        require_id(servo_id)?;
        let frame = self.tx_rx(servo_id, INST_PING, &[], self.timeout).await?;
        if frame.id != servo_id {
            return Err(Error::UnexpectedId);
        }
        Ok(())
    }

    pub async fn write_position(
        &mut self,
        servo_id: u8,
        position: u16,
        speed: u16,
        acc: u8,
    ) -> Result<(), Error<B::Error>> {
        require_id(servo_id)?;
        let position = position.min(MAX_POSITION);
        let params = [
            SMS_STS_ACC,
            acc,
            low_byte(position),
            high_byte(position),
            0,
            0,
            low_byte(speed),
            high_byte(speed),
        ];
        self.write_checked(servo_id, &params).await
    }

    pub async fn write_angle(
        &mut self,
        servo_id: u8,
        angle_deg: u16,
        speed: u16,
        acc: u8,
    ) -> Result<(), Error<B::Error>> {
        self.write_position(servo_id, angle_to_position(angle_deg), speed, acc)
            .await
    }

    pub async fn set_mode(&mut self, servo_id: u8, mode: Mode) -> Result<(), Error<B::Error>> {
        let value = match mode {
            Mode::Position => 0,
            Mode::Wheel => 1,
        };
        self.write_u8(servo_id, SMS_STS_MODE, value).await
    }

    pub async fn write_wheel_speed(
        &mut self,
        servo_id: u8,
        speed: i16,
        acc: u8,
    ) -> Result<(), Error<B::Error>> {
        require_id(servo_id)?;
        let speed = to_servo_signed(speed);
        let params = [
            SMS_STS_ACC,
            acc,
            0,
            0,
            0,
            0,
            low_byte(speed),
            high_byte(speed),
        ];
        self.write_checked(servo_id, &params).await
    }

    pub async fn write_id(&mut self, old_id: u8, new_id: u8) -> Result<(), Error<B::Error>> {
        require_id(old_id)?;
        require_id(new_id)?;
        self.write_u8(old_id, SMS_STS_ID, new_id).await
    }

    pub async fn lock_eeprom(&mut self, servo_id: u8) -> Result<(), Error<B::Error>> {
        self.write_u8(servo_id, SMS_STS_LOCK, 1).await
    }

    pub async fn unlock_eeprom(&mut self, servo_id: u8) -> Result<(), Error<B::Error>> {
        self.write_u8(servo_id, SMS_STS_LOCK, 0).await
    }

    pub async fn read_position(&mut self, servo_id: u8) -> Result<u16, Error<B::Error>> {
        let data = self
            .read::<2>(servo_id, SMS_STS_PRESENT_POSITION_L, 2)
            .await?;
        Ok(u16::from_le_bytes([data[0], data[1]]))
    }

    pub async fn read_status(&mut self, servo_id: u8) -> Result<Status, Error<B::Error>> {
        let voltage = self.read_u8(servo_id, SMS_STS_PRESENT_VOLTAGE).await?;
        let temperature = self.read_u8(servo_id, SMS_STS_PRESENT_TEMPERATURE).await?;
        Ok(Status {
            voltage_raw: voltage,
            temperature_c: temperature,
        })
    }

    pub async fn write_u8(
        &mut self,
        servo_id: u8,
        address: u8,
        value: u8,
    ) -> Result<(), Error<B::Error>> {
        self.write_bytes(servo_id, address, &[value]).await
    }

    pub async fn write_bytes(
        &mut self,
        servo_id: u8,
        address: u8,
        data: &[u8],
    ) -> Result<(), Error<B::Error>> {
        require_id(servo_id)?;
        if data.len() > MAX_PARAMS - 1 {
            return Err(Error::PacketTooLarge);
        }

        let mut params = [0u8; MAX_PARAMS];
        params[0] = address;
        params[1..1 + data.len()].copy_from_slice(data);
        self.write_checked(servo_id, &params[..1 + data.len()])
            .await
    }

    pub async fn read_u8(&mut self, servo_id: u8, address: u8) -> Result<u8, Error<B::Error>> {
        let data = self.read::<1>(servo_id, address, 1).await?;
        Ok(data[0])
    }

    pub async fn read<const N: usize>(
        &mut self,
        servo_id: u8,
        address: u8,
        len: u8,
    ) -> Result<[u8; N], Error<B::Error>> {
        require_id(servo_id)?;
        if len as usize != N || N > MAX_PARAMS {
            return Err(Error::InvalidPacket);
        }

        let frame = self
            .tx_rx(servo_id, INST_READ, &[address, len], self.timeout)
            .await?;
        if frame.id != servo_id {
            return Err(Error::UnexpectedId);
        }
        if frame.error != 0 {
            return Err(Error::Status(frame.error));
        }
        if frame.params_len < N {
            return Err(Error::InvalidPacket);
        }

        let mut out = [0u8; N];
        out.copy_from_slice(&frame.params[..N]);
        Ok(out)
    }

    async fn write_checked(&mut self, servo_id: u8, params: &[u8]) -> Result<(), Error<B::Error>> {
        let frame = self
            .tx_rx(servo_id, INST_WRITE, params, self.timeout)
            .await?;
        if frame.id != servo_id {
            return Err(Error::UnexpectedId);
        }
        if frame.error != 0 {
            return Err(Error::Status(frame.error));
        }
        Ok(())
    }

    async fn tx_rx(
        &mut self,
        servo_id: u8,
        instruction: u8,
        params: &[u8],
        timeout: Duration,
    ) -> Result<Frame, Error<B::Error>> {
        let mut packet = [0u8; MAX_PACKET_LEN];
        let packet_len = build_packet(&mut packet, servo_id, instruction, params)
            .map_err(|err| err.with_error())?;

        self.drain_rx()?;
        self.bus
            .write_all(&packet[..packet_len])
            .map_err(Error::Io)?;

        if servo_id == BROADCAST_ID {
            return Ok(Frame::default());
        }

        read_frame(&mut self.bus, timeout).await
    }

    fn drain_rx(&mut self) -> Result<(), Error<B::Error>> {
        let mut buf = [0u8; 32];
        loop {
            let read = self.bus.read_buffered(&mut buf).map_err(Error::Io)?;
            if read == 0 {
                return Ok(());
            }
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Frame {
    pub id: u8,
    pub error: u8,
    pub params: [u8; MAX_PARAMS],
    pub params_len: usize,
}

impl Default for Frame {
    fn default() -> Self {
        Self {
            id: 0,
            error: 0,
            params: [0u8; MAX_PARAMS],
            params_len: 0,
        }
    }
}

pub fn angle_to_position(angle_deg: u16) -> u16 {
    let clamped = angle_deg.min(240) as u32;
    ((clamped * MAX_POSITION as u32) / 240) as u16
}

pub fn build_packet(
    out: &mut [u8],
    servo_id: u8,
    instruction: u8,
    params: &[u8],
) -> Result<usize, Error<core::convert::Infallible>> {
    if params.len() > MAX_PACKET_LEN - 6 {
        return Err(Error::PacketTooLarge);
    }

    let len = params.len() + 2;
    let frame_len = len + 4;
    if out.len() < frame_len {
        return Err(Error::PacketTooLarge);
    }

    out[0..2].copy_from_slice(&HEADER);
    out[2] = servo_id;
    out[3] = len as u8;
    out[4] = instruction;
    out[5..5 + params.len()].copy_from_slice(params);
    out[frame_len - 1] = checksum(&out[..frame_len - 1]);
    Ok(frame_len)
}

async fn read_frame<B>(bus: &mut B, timeout: Duration) -> Result<Frame, Error<B::Error>>
where
    B: SerialBus,
{
    let deadline = Instant::now() + timeout;
    let mut state = ParseState::Header0;
    let mut frame = Frame::default();
    let mut sum = 0u8;
    let mut params_needed = 0usize;
    let mut param_i = 0usize;
    let mut byte = [0u8; 1];

    loop {
        if Instant::now() >= deadline {
            return Err(Error::Timeout);
        }

        match bus.read_buffered(&mut byte).map_err(Error::Io)? {
            0 => {
                Timer::after(Duration::from_millis(1)).await;
                continue;
            }
            _ => {}
        }

        let b = byte[0];
        match state {
            ParseState::Header0 => {
                if b == HEADER[0] {
                    state = ParseState::Header1;
                }
            }
            ParseState::Header1 => {
                state = if b == HEADER[1] {
                    ParseState::Id
                } else if b == HEADER[0] {
                    ParseState::Header1
                } else {
                    ParseState::Header0
                };
            }
            ParseState::Id => {
                if b > 0xfd {
                    state = ParseState::Header0;
                    continue;
                }
                frame.id = b;
                sum = b;
                state = ParseState::Len;
            }
            ParseState::Len => {
                if b < 2 || b as usize > MAX_PACKET_LEN {
                    state = ParseState::Header0;
                    continue;
                }
                sum = sum.wrapping_add(b);
                params_needed = (b as usize) - 2;
                if params_needed > MAX_PARAMS {
                    return Err(Error::PacketTooLarge);
                }
                frame.params_len = params_needed;
                state = ParseState::Error;
            }
            ParseState::Error => {
                frame.error = b;
                sum = sum.wrapping_add(b);
                param_i = 0;
                state = if params_needed == 0 {
                    ParseState::Checksum
                } else {
                    ParseState::Params
                };
            }
            ParseState::Params => {
                frame.params[param_i] = b;
                sum = sum.wrapping_add(b);
                param_i += 1;
                if param_i >= params_needed {
                    state = ParseState::Checksum;
                }
            }
            ParseState::Checksum => {
                if b != !sum {
                    return Err(Error::Checksum);
                }
                return Ok(frame);
            }
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ParseState {
    Header0,
    Header1,
    Id,
    Len,
    Error,
    Params,
    Checksum,
}

fn require_id<E>(servo_id: u8) -> Result<(), Error<E>> {
    if (MIN_SERVO_ID..=MAX_SERVO_ID).contains(&servo_id) {
        Ok(())
    } else {
        Err(Error::InvalidId)
    }
}

fn checksum(packet_without_checksum: &[u8]) -> u8 {
    let mut sum = 0u8;
    for byte in packet_without_checksum.iter().skip(2) {
        sum = sum.wrapping_add(*byte);
    }
    !sum
}

fn low_byte(value: u16) -> u8 {
    (value & 0xff) as u8
}

fn high_byte(value: u16) -> u8 {
    (value >> 8) as u8
}

fn to_servo_signed(value: i16) -> u16 {
    if value < 0 {
        cmp::min((-value) as u16, 0x7fff) | 0x8000
    } else {
        cmp::min(value as u16, 0x7fff)
    }
}
