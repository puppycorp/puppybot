use super::{
    kinematics::{self, IkError},
    servo_safety::{SafetyFault, TICK_WRAP, align_tick_to_reference, continuous_tick_interval},
};
use core::f64::consts::PI;

pub const JOINT_COUNT: usize = 4;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TcpFrame {
    Base,
    YawFlat,
    Tool,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ArmCommand {
    SetSpeed(i16),
    Spin {
        joint: usize,
        direction: i8,
    },
    Stop {
        joint: usize,
    },
    StopAll,
    GotoTicks([i32; JOINT_COUNT]),
    GotoAngles([f64; JOINT_COUNT]),
    GotoCoords {
        x: f64,
        y: f64,
        z: f64,
        tool_phi_rad: f64,
    },
    MoveTcp {
        frame: TcpFrame,
        dx_mm: f64,
        dy_mm: f64,
        dz_mm: f64,
    },
    StartTcpJog {
        frame: TcpFrame,
        direction: [f64; 3],
    },
    StartTcpJogAtSpeed {
        frame: TcpFrame,
        direction: [f64; 3],
        speed_mm_s: f64,
    },
    StopTcpJog,
    Hold,
    SetJointTick {
        joint: usize,
        tick: i32,
    },
    SetJointAngle {
        joint: usize,
        angle_rad: f64,
    },
    SetJointReference {
        joint: usize,
        tick: i32,
        angle_rad: f64,
    },
    SetServoAngle {
        servo_id: u8,
        angle_rad: f64,
        speed: i16,
    },
    SetTickLimits {
        joint: usize,
        min: i32,
        max: i32,
    },
    SetTickLimitsEnabled {
        joint: usize,
        enabled: bool,
    },
    ClearFaults {
        joint: Option<usize>,
    },
    SetServoIds([u8; JOINT_COUNT]),
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ArmMode {
    Idle,
    Jogging {
        joint: usize,
        direction: i8,
    },
    TrackingTicks {
        targets: [i32; JOINT_COUNT],
    },
    TcpJogging {
        frame: TcpFrame,
        direction: [f64; 3],
        speed_override_mm_s: Option<f64>,
        last_step_ms: u64,
        target_angles: [f64; JOINT_COUNT],
        target_coords_mm: [f64; 3],
        tool_pitch_rad: f64,
    },
    Holding {
        targets: [i32; JOINT_COUNT],
    },
    Fault,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct JointLimitViolation {
    pub joint: usize,
    pub requested_tick: i32,
    pub tick_min: i32,
    pub tick_max: i32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CartesianJointLimitError {
    pub candidate_ticks: [i32; JOINT_COUNT],
    pub violations: [Option<JointLimitViolation>; JOINT_COUNT],
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum ControllerError {
    InvalidJoint,
    InvalidServoIds,
    InvalidLimit,
    MissingFeedback,
    Ik(IkError),
    CartesianJointLimits(CartesianJointLimitError),
}

impl From<IkError> for ControllerError {
    fn from(err: IkError) -> Self {
        Self::Ik(err)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PuppyarmTelemetry {
    pub seq: u32,
    pub joints: [Joint; JOINT_COUNT],
    pub coords_mm: Option<(f32, f32, f32)>,
    pub target_coords_mm: Option<(f32, f32, f32)>,
    pub effective_target_coords_mm: Option<(f32, f32, f32)>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Joint {
    pub servo_id: u8,
    pub tick_min: i32,
    pub tick_max: i32,
    pub raw_tick_min: i32,
    pub raw_tick_max: i32,
    pub sign: f64,
    pub drive_sign: i8,
    pub reference_tick: i32,
    pub reference_angle_rad: f64,
    pub zero_offset_rad: f64,
    pub online: bool,
    pub has_feedback: bool,
    pub limit_reached: bool,
    pub tick: Option<i32>,
    pub angle_rad: Option<f64>,
    pub target_tick: Option<i32>,
    pub target_angle_rad: Option<f64>,
    pub tick_delta: i32,
    pub limit_enabled: bool,
    pub speed: i16,
    pub limit_min: i32,
    pub limit_max: i32,
    pub last_feedback_ms: u64,
    pub temp_c: Option<u8>,
    pub last_sent_speed: Option<i16>,
    pub last_speed_cmd_ms: u64,
    pub stall_since_ms: Option<u64>,
    pub fault: Option<SafetyFault>,
}

impl Joint {
    pub const fn new(servo_id: u8, tick_min: i32, tick_max: i32) -> Self {
        Self {
            servo_id,
            tick_min,
            tick_max,
            raw_tick_min: tick_min,
            raw_tick_max: tick_max,
            sign: 1.0,
            drive_sign: 1,
            reference_tick: tick_min,
            reference_angle_rad: 0.0,
            zero_offset_rad: 0.0,
            online: true,
            has_feedback: false,
            limit_reached: false,
            tick: None,
            angle_rad: None,
            target_tick: None,
            target_angle_rad: None,
            tick_delta: 0,
            limit_enabled: true,
            speed: 0,
            limit_min: tick_min,
            limit_max: tick_max,
            last_feedback_ms: 0,
            temp_c: None,
            last_sent_speed: None,
            last_speed_cmd_ms: 0,
            stall_since_ms: None,
            fault: None,
        }
    }

    pub const fn with_drive_sign(mut self, drive_sign: i8) -> Self {
        self.drive_sign = drive_sign;
        self
    }

    pub fn record_feedback(&mut self, tick: i32, now_ms: u64) {
        let previous = self.tick;
        self.tick = Some(tick);
        self.tick_delta = previous.map(|value| tick - value).unwrap_or(0);
        self.has_feedback = true;
        self.online = true;
        self.last_feedback_ms = now_ms;
    }

    pub fn record_feedback_error(&mut self) {
        self.online = false;
        self.tick = None;
        self.angle_rad = None;
        self.tick_delta = 0;
    }

    pub fn set_temperature(&mut self, temp_c: Option<u8>) {
        self.temp_c = temp_c;
    }

    pub fn clear_fault(&mut self) {
        self.fault = None;
        self.stall_since_ms = None;
    }

    pub fn clear_target(&mut self) {
        self.target_tick = None;
        self.target_angle_rad = None;
    }

    pub fn stop(&mut self) {
        self.clear_target();
        self.speed = 0;
    }

    pub fn spin(&mut self, direction: i8, default_speed: i16) {
        self.clear_fault();
        self.clear_target();
        self.speed = direction.signum() as i16 * default_speed.abs();
    }

    pub fn angle_deg(&self) -> Option<f32> {
        self.angle_rad.map(display_degrees)
    }

    pub fn target_angle_deg(&self) -> Option<f32> {
        self.target_angle_rad.map(display_degrees)
    }

    fn reference_mid_tick(&self) -> f64 {
        let (lo, hi) = continuous_tick_interval(self.raw_tick_min, self.raw_tick_max);
        0.5 * (lo + hi) as f64
    }

    pub fn angle_to_tick(&self, angle_rad: f64) -> i32 {
        let mid_tick = self.reference_mid_tick();
        let physical_angle = self.sign * angle_rad + self.zero_offset_rad;
        libm::round(mid_tick + physical_angle * TICK_WRAP as f64 / (2.0 * PI)) as i32
    }

    pub fn tick_to_angle(&self, tick: i32) -> f64 {
        let mid_tick = self.reference_mid_tick();
        let aligned_tick = align_tick_to_reference(tick, mid_tick as i32);
        let physical_angle = (aligned_tick as f64 - mid_tick) * (2.0 * PI / TICK_WRAP as f64);
        (physical_angle - self.zero_offset_rad) / self.sign
    }
}

fn display_degrees(angle_rad: f64) -> f32 {
    (kinematics::wrap_pi(angle_rad) * 180.0 / core::f64::consts::PI) as f32
}
