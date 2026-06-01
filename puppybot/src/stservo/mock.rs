#![allow(dead_code)]

extern crate alloc;

use core::future::Future;
use core::pin::Pin;
use core::task::{Context, Poll, RawWaker, RawWakerVTable, Waker};

use alloc::vec;
use alloc::vec::Vec;

use super::*;

const FAKE_MAX_PACKET: usize = 128;
const FAKE_MAX_READ: usize = 512;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct FakeServo {
    pub(crate) id: u8,
    pub(crate) mode: Mode,
    pub(crate) position: u16,
    pub(crate) wheel_speed: i16,
    pub(crate) online: bool,
}

impl FakeServo {
    pub(crate) fn new(id: u8, position: u16) -> Self {
        Self {
            id,
            mode: Mode::Position,
            position,
            wheel_speed: 0,
            online: true,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum FakeBusError {
    PacketTooLarge,
    BadPacket,
}

#[derive(Clone, Debug)]
pub(crate) struct FakeSerialBus {
    servos: [Option<FakeServo>; 8],
    pub(crate) writes: Vec<Vec<u8>>,
    read_buf: [u8; FAKE_MAX_READ],
    read_start: usize,
    read_end: usize,
}

impl FakeSerialBus {
    pub(crate) fn new() -> Self {
        Self {
            servos: [None; 8],
            writes: Vec::new(),
            read_buf: [0; FAKE_MAX_READ],
            read_start: 0,
            read_end: 0,
        }
    }

    pub(crate) fn with_servo(mut self, id: u8, position: u16) -> Self {
        self.set_servo(FakeServo::new(id, position));
        self
    }

    pub(crate) fn servo(&self, id: u8) -> Option<FakeServo> {
        self.servos
            .iter()
            .flatten()
            .find(|servo| servo.id == id)
            .copied()
    }

    pub(crate) fn set_servo(&mut self, servo: FakeServo) {
        if let Some(slot) = self
            .servos
            .iter_mut()
            .find(|slot| slot.map(|existing| existing.id) == Some(servo.id))
        {
            *slot = Some(servo);
            return;
        }

        let slot = self
            .servos
            .iter_mut()
            .find(|slot| slot.is_none())
            .expect("fake servo capacity exceeded");
        *slot = Some(servo);
    }

    fn servo_mut(&mut self, id: u8) -> Option<&mut FakeServo> {
        self.servos
            .iter_mut()
            .flatten()
            .find(|servo| servo.id == id)
    }

    fn handle_packet(&mut self, packet: &[u8]) -> Result<(), FakeBusError> {
        if packet.len() < 6
            || packet[0..2] != HEADER
            || packet[packet.len() - 1] != checksum(&packet[..packet.len() - 1])
        {
            return Err(FakeBusError::BadPacket);
        }

        let id = packet[2];
        let len = packet[3] as usize;
        if len + 4 != packet.len() {
            return Err(FakeBusError::BadPacket);
        }

        let instruction = packet[4];
        let params = &packet[5..packet.len() - 1];

        let Some(servo) = self.servo_mut(id) else {
            return Ok(());
        };
        if !servo.online {
            return Ok(());
        }

        match instruction {
            INST_PING => self.queue_status(id, 0, &[])?,
            INST_READ => {
                if params.len() < 2 {
                    return Err(FakeBusError::BadPacket);
                }
                let address = params[0];
                let read_len = params[1];
                let mut response = [0u8; 4];
                let response = match (address, read_len) {
                    (SMS_STS_PRESENT_POSITION_L, 2) => {
                        response[0..2].copy_from_slice(&servo.position.to_le_bytes());
                        &response[..2]
                    }
                    (SMS_STS_MODE, 1) => {
                        response[0] = match servo.mode {
                            Mode::Position => 0,
                            Mode::Wheel => 1,
                        };
                        &response[..1]
                    }
                    _ => return Err(FakeBusError::BadPacket),
                };
                self.queue_status(id, 0, response)?;
            }
            INST_WRITE => {
                if params.is_empty() {
                    return Err(FakeBusError::BadPacket);
                }
                let address = params[0];
                let data = &params[1..];
                match address {
                    SMS_STS_MODE if data.len() == 1 => {
                        servo.mode = if data[0] == 0 {
                            Mode::Position
                        } else {
                            Mode::Wheel
                        };
                    }
                    SMS_STS_ACC if data.len() >= 7 => {
                        let position = u16::from_le_bytes([data[1], data[2]]);
                        let speed = u16::from_le_bytes([data[5], data[6]]);
                        if servo.mode == Mode::Wheel {
                            servo.wheel_speed = from_servo_signed(speed);
                        } else {
                            servo.position = position.min(MAX_POSITION);
                        }
                    }
                    _ => {}
                }
                self.queue_status(id, 0, &[])?;
            }
            _ => return Err(FakeBusError::BadPacket),
        }

        Ok(())
    }

    fn queue_status(&mut self, id: u8, status: u8, params: &[u8]) -> Result<(), FakeBusError> {
        let mut frame = [0u8; FAKE_MAX_PACKET];
        frame[0..2].copy_from_slice(&HEADER);
        frame[2] = id;
        frame[3] = (params.len() + 2) as u8;
        frame[4] = status;
        frame[5..5 + params.len()].copy_from_slice(params);
        let frame_len = params.len() + 6;
        frame[frame_len - 1] = checksum(&frame[..frame_len - 1]);
        self.queue_read(&frame[..frame_len])
    }

    pub(crate) fn queue_read(&mut self, bytes: &[u8]) -> Result<(), FakeBusError> {
        if self.read_end + bytes.len() > self.read_buf.len() {
            return Err(FakeBusError::PacketTooLarge);
        }
        self.read_buf[self.read_end..self.read_end + bytes.len()].copy_from_slice(bytes);
        self.read_end += bytes.len();
        Ok(())
    }
}

impl SerialBus for FakeSerialBus {
    type Error = FakeBusError;

    fn write(&mut self, bytes: &[u8]) -> Result<usize, Self::Error> {
        self.writes.push(bytes.to_vec());
        self.handle_packet(bytes)?;
        Ok(bytes.len())
    }

    fn flush(&mut self) -> Result<(), Self::Error> {
        Ok(())
    }

    fn read_buffered(&mut self, bytes: &mut [u8]) -> Result<usize, Self::Error> {
        if self.read_start == self.read_end {
            self.read_start = 0;
            self.read_end = 0;
            return Ok(0);
        }

        let len = bytes.len().min(self.read_end - self.read_start);
        bytes[..len].copy_from_slice(&self.read_buf[self.read_start..self.read_start + len]);
        self.read_start += len;
        Ok(len)
    }
}

#[test]
fn fake_serial_bus_records_real_set_mode_packet() {
    let mut bus = FakeSerialBus::new().with_servo(1, 1234);

    let packet = packet(1, INST_WRITE, &[SMS_STS_MODE, 1]);
    bus.write_all(&packet).unwrap();

    assert_eq!(bus.writes, vec![packet]);
    assert_eq!(bus.servo(1).unwrap().mode, Mode::Wheel);

    let mut response = [0u8; 6];
    assert_eq!(bus.read_buffered(&mut response).unwrap(), 6);
    assert_eq!(response, status_packet(1, 0, &[]));
}

#[test]
fn fake_serial_bus_queues_position_response_at_byte_level() {
    let mut bus = FakeSerialBus::new().with_servo(2, 0x1234);

    let packet = packet(2, INST_READ, &[SMS_STS_PRESENT_POSITION_L, 2]);
    bus.write_all(&packet).unwrap();

    let expected = status_packet(2, 0, &[0x34, 0x12]);
    let mut response = [0u8; 8];
    assert_eq!(bus.read_buffered(&mut response).unwrap(), expected.len());
    assert_eq!(&response[..expected.len()], expected.as_slice());
}

#[test]
fn set_mode_uses_fake_serial_bus_end_to_end() {
    let mut servo = StServo::new(FakeSerialBus::new().with_servo(3, 0));

    block_on_ready(servo.set_mode(3, Mode::Wheel)).unwrap();

    assert_eq!(servo.bus_mut().servo(3).unwrap().mode, Mode::Wheel);
    assert_eq!(
        servo.bus_mut().writes[0],
        packet(3, INST_WRITE, &[SMS_STS_MODE, 1])
    );
}

#[test]
fn read_position_uses_fake_serial_bus_end_to_end() {
    let mut servo = StServo::new(FakeSerialBus::new().with_servo(4, 0x0abc));

    let position = block_on_ready(servo.read_position(4)).unwrap();

    assert_eq!(position, 0x0abc);
    assert_eq!(
        servo.bus_mut().writes[0],
        packet(4, INST_READ, &[SMS_STS_PRESENT_POSITION_L, 2])
    );
}

#[test]
fn write_wheel_speed_updates_fake_servo_from_real_packet() {
    let mut servo = StServo::new(FakeSerialBus::new().with_servo(1, 0));

    block_on_ready(servo.set_mode(1, Mode::Wheel)).unwrap();
    block_on_ready(servo.write_wheel_speed(1, -120, 7)).unwrap();

    let fake = servo.bus_mut().servo(1).unwrap();
    assert_eq!(fake.mode, Mode::Wheel);
    assert_eq!(fake.wheel_speed, -120);
    assert_eq!(
        servo.bus_mut().writes[1],
        packet(1, INST_WRITE, &[SMS_STS_ACC, 7, 0, 0, 0, 0, 120, 0x80])
    );
}

#[test]
fn servo_id_zero_is_rejected_before_bus_write() {
    let mut servo = StServo::new(FakeSerialBus::new());

    assert_eq!(
        block_on_ready(servo.set_mode(0, Mode::Wheel)),
        Err(Error::InvalidId)
    );
    assert!(servo.bus_mut().writes.is_empty());
}

pub(crate) fn packet(id: u8, instruction: u8, params: &[u8]) -> Vec<u8> {
    let mut out = [0u8; FAKE_MAX_PACKET];
    let len = build_packet(&mut out, id, instruction, params).unwrap();
    out[..len].to_vec()
}

pub(crate) fn status_packet(id: u8, status: u8, params: &[u8]) -> Vec<u8> {
    let mut out = vec![0xff, 0xff, id, (params.len() + 2) as u8, status];
    out.extend_from_slice(params);
    let crc = checksum(&out);
    out.push(crc);
    out
}

fn from_servo_signed(value: u16) -> i16 {
    let magnitude = (value & 0x7fff) as i16;
    if (value & 0x8000) != 0 {
        -magnitude
    } else {
        magnitude
    }
}

pub(crate) fn block_on_ready<F: Future>(future: F) -> F::Output {
    let waker = noop_waker();
    let mut context = Context::from_waker(&waker);
    let mut future = core::pin::pin!(future);
    match Pin::new(&mut future).poll(&mut context) {
        Poll::Ready(output) => output,
        Poll::Pending => panic!("test future unexpectedly pending"),
    }
}

fn noop_waker() -> Waker {
    unsafe fn clone(_: *const ()) -> RawWaker {
        raw_waker()
    }
    unsafe fn wake(_: *const ()) {}
    unsafe fn wake_by_ref(_: *const ()) {}
    unsafe fn drop(_: *const ()) {}

    fn raw_waker() -> RawWaker {
        RawWaker::new(
            core::ptr::null(),
            &RawWakerVTable::new(clone, wake, wake_by_ref, drop),
        )
    }

    unsafe { Waker::from_raw(raw_waker()) }
}
