mod client;

use std::time::Duration;

use anyhow::{Result, bail};
use clap::{Args, Parser, Subcommand, ValueEnum};
use client::{ArmState, RuntimeClient, RuntimeFrame};
use puppybot_core::protocol::{
    CMD_ARM_CLEAR_FAULTS, CMD_ARM_GOTO_ANGLES, CMD_ARM_GOTO_COORDS, CMD_ARM_GOTO_TICKS,
    CMD_ARM_HOLD, CMD_ARM_JOG, CMD_ARM_MOVE_RELATIVE, CMD_ARM_SET_JOINT_TICK, CMD_ARM_STOP,
    CMD_ARM_STOP_JOINT, CMD_CONFIG_GET, CMD_CONFIG_SET, CMD_DRIVE_STEER, CMD_PING, CMD_SERVO_SET,
    CMD_STOP_DRIVE, CONFIG_VERSION, RobotConfig,
};

const DEFAULT_URL: &str = "ws://127.0.0.1:8080/ws";
const DEFAULT_TIMEOUT_MS: u64 = 1500;

#[derive(Debug, Parser)]
#[command(name = "puppybot", about = "Puppybot runtime CLI")]
struct Cli {
    #[arg(long, default_value = DEFAULT_URL)]
    url: String,

    #[arg(long, default_value_t = DEFAULT_TIMEOUT_MS)]
    timeout_ms: u64,

    #[command(subcommand)]
    command: Command,
}

#[derive(Debug, Subcommand)]
enum Command {
    Ping,
    WsPing,
    #[command(subcommand)]
    Config(ConfigCommand),
    #[command(subcommand)]
    Arm(ArmCommand),
    #[command(subcommand)]
    Drive(DriveCommand),
}

#[derive(Debug, Subcommand)]
enum ConfigCommand {
    Get,
    Set(ConfigSetArgs),
}

#[derive(Debug, Args)]
struct ConfigSetArgs {
    #[arg(long, default_value_t = 1)]
    steering_servo_id: u8,

    #[arg(long, value_delimiter = ',', num_args = 4)]
    arm_servo_ids: Vec<u8>,
}

#[derive(Debug, Subcommand)]
enum ArmCommand {
    State,
    Jog(JogArgs),
    Stop(StopArgs),
    Hold(SpeedArgs),
    GotoTicks(GotoTicksArgs),
    GotoAngles(GotoAnglesArgs),
    GotoCoords(GotoCoordsArgs),
    MoveTcp(MoveTcpArgs),
    SetJointTick(SetJointTickArgs),
    ClearFaults(ClearFaultsArgs),
    ServoSet(ServoSetArgs),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
enum TcpFrameArg {
    Base,
    Tool,
}

#[derive(Debug, Args)]
struct JogArgs {
    #[arg(long)]
    joint: u8,

    #[arg(long)]
    direction: i8,

    #[arg(long, default_value_t = 300)]
    speed: u16,

    #[arg(long)]
    duration_ms: Option<u64>,
}

#[derive(Debug, Args)]
struct StopArgs {
    #[arg(long)]
    joint: Option<u8>,
}

#[derive(Debug, Args)]
struct SpeedArgs {
    #[arg(long, default_value_t = 300)]
    speed: u16,
}

#[derive(Debug, Args)]
struct GotoTicksArgs {
    #[arg(long, default_value_t = 300)]
    speed: u16,

    #[arg(num_args = 4)]
    ticks: Vec<i32>,
}

#[derive(Debug, Args)]
struct GotoAnglesArgs {
    #[arg(long, default_value_t = 300)]
    speed: u16,

    #[arg(num_args = 4)]
    degrees: Vec<f32>,
}

#[derive(Debug, Args)]
struct GotoCoordsArgs {
    x: f32,
    y: f32,
    z: f32,

    #[arg(long, default_value_t = 300)]
    speed: u16,
}

#[derive(Debug, Args)]
struct MoveTcpArgs {
    #[arg(long, value_enum, default_value = "base")]
    frame: TcpFrameArg,

    #[arg(long, default_value_t = 0.0)]
    up: f32,

    #[arg(long, default_value_t = 0.0)]
    down: f32,

    #[arg(long, default_value_t = 0.0)]
    left: f32,

    #[arg(long, default_value_t = 0.0)]
    right: f32,

    #[arg(long, default_value_t = 0.0)]
    forward: f32,

    #[arg(long, default_value_t = 0.0)]
    back: f32,

    #[arg(long, default_value_t = 300)]
    speed: u16,
}

#[derive(Debug, Args)]
struct SetJointTickArgs {
    #[arg(long)]
    joint: u8,

    #[arg(long)]
    tick: i32,

    #[arg(long, default_value_t = 300)]
    speed: u16,
}

#[derive(Debug, Args)]
struct ClearFaultsArgs {
    #[arg(long)]
    joint: Option<u8>,
}

#[derive(Debug, Args)]
struct ServoSetArgs {
    #[arg(long)]
    servo_id: u8,

    #[arg(long)]
    angle_deg: u16,

    #[arg(long, default_value_t = 500)]
    duration_ms: u16,
}

#[derive(Debug, Subcommand)]
enum DriveCommand {
    Steer(DriveSteerArgs),
    Stop,
}

#[derive(Debug, Args)]
struct DriveSteerArgs {
    #[arg(long)]
    throttle: i8,

    #[arg(long)]
    steering: i8,
}

fn push_u16_le(out: &mut Vec<u8>, value: u16) {
    out.extend_from_slice(&value.to_le_bytes());
}

fn push_i32_le(out: &mut Vec<u8>, value: i32) {
    out.extend_from_slice(&value.to_le_bytes());
}

fn push_f32_le(out: &mut Vec<u8>, value: f32) {
    out.extend_from_slice(&value.to_le_bytes());
}

fn tcp_frame_id(frame: TcpFrameArg) -> u8 {
    match frame {
        TcpFrameArg::Base => 0,
        TcpFrameArg::Tool => 1,
    }
}

fn move_tcp_delta(args: &MoveTcpArgs) -> (f32, f32, f32) {
    match args.frame {
        TcpFrameArg::Base => (
            args.back - args.forward,
            args.left - args.right,
            args.up - args.down,
        ),
        TcpFrameArg::Tool => (
            args.forward - args.back,
            args.left - args.right,
            args.up - args.down,
        ),
    }
}

fn move_tcp_body(args: &MoveTcpArgs) -> Vec<u8> {
    let (dx, dy, dz) = move_tcp_delta(args);
    let mut body = Vec::new();
    push_u16_le(&mut body, args.speed);
    body.push(tcp_frame_id(args.frame));
    push_f32_le(&mut body, dx);
    push_f32_le(&mut body, dy);
    push_f32_le(&mut body, dz);
    body
}

fn print_config(config: RobotConfig) {
    println!("steering_servo_id={}", config.steering_servo_id);
    println!(
        "arm_servo_ids={},{},{},{}",
        config.arm_servo_ids[0],
        config.arm_servo_ids[1],
        config.arm_servo_ids[2],
        config.arm_servo_ids[3]
    );
}

fn print_arm_state(state: ArmState) {
    println!("servo\tonline\tfeedback\ttick\ttarget\tspeed\tlimits\tangle\tfault");
    for joint in state.joints {
        let target = joint
            .target_tick
            .map(|value| value.to_string())
            .unwrap_or_else(|| "-".to_string());
        let fault = joint.fault.unwrap_or_else(|| {
            if joint.has_fault {
                "unknown".to_string()
            } else {
                "-".to_string()
            }
        });
        let online = if joint.online { "yes" } else { "no" };
        let feedback = if joint.has_feedback { "yes" } else { "no" };
        let limit = if joint.limit_reached { "!" } else { "" };
        println!(
            "{}\t{}\t{}\t{}\t{}\t{}\t{}..{}{}\t{:.2}\t{}",
            joint.servo_id,
            online,
            feedback,
            joint.tick,
            target,
            joint.speed,
            joint.limit_min,
            joint.limit_max,
            limit,
            joint.angle_deg,
            fault
        );
    }
    if let Some([x, y, z]) = state.coords_mm {
        println!("coords_mm={x:.1},{y:.1},{z:.1}");
    }
}

async fn wait_for_config(client: &mut RuntimeClient, timeout: Duration) -> Result<RobotConfig> {
    loop {
        match client.read_frame(timeout).await? {
            RuntimeFrame::Config(config) => return Ok(config),
            RuntimeFrame::Text(text) => println!("{text}"),
            RuntimeFrame::Binary(payload) => println!("binary response: {} bytes", payload.len()),
            RuntimeFrame::Pong | RuntimeFrame::ArmState(_) => {}
        }
    }
}

async fn wait_for_arm_state(client: &mut RuntimeClient, timeout: Duration) -> Result<ArmState> {
    loop {
        match client.read_frame(timeout).await? {
            RuntimeFrame::ArmState(state) => return Ok(state),
            RuntimeFrame::Text(text) => println!("{text}"),
            RuntimeFrame::Binary(payload) => println!("binary response: {} bytes", payload.len()),
            RuntimeFrame::Pong | RuntimeFrame::Config(_) => {}
        }
    }
}

fn arm_servo_ids(ids: Vec<u8>) -> Result<[u8; 4]> {
    let ids: [u8; 4] = ids
        .try_into()
        .map_err(|_| anyhow::anyhow!("--arm-servo-ids requires exactly four values"))?;
    if ids.contains(&0) {
        bail!("servo id 0 is invalid");
    }
    Ok(ids)
}

async fn send_arm_command(
    client: &mut RuntimeClient,
    command: u8,
    body: &[u8],
    label: &str,
) -> Result<()> {
    client.send_command(command, body).await?;
    println!("sent {label}");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(frame: TcpFrameArg) -> MoveTcpArgs {
        MoveTcpArgs {
            frame,
            up: 0.0,
            down: 0.0,
            left: 0.0,
            right: 0.0,
            forward: 0.0,
            back: 0.0,
            speed: 300,
        }
    }

    #[test]
    fn base_move_tcp_aliases_map_to_table_delta() {
        let mut args = args(TcpFrameArg::Base);
        args.up = 20.0;
        args.forward = 30.0;
        args.left = 5.0;

        assert_eq!(move_tcp_delta(&args), (-30.0, 5.0, 20.0));
    }

    #[test]
    fn tool_move_tcp_forward_maps_to_tool_x_delta() {
        let mut args = args(TcpFrameArg::Tool);
        args.forward = 20.0;
        args.back = 5.0;

        assert_eq!(move_tcp_delta(&args), (15.0, 0.0, 0.0));
    }

    #[test]
    fn move_tcp_body_encodes_tool_frame() {
        let mut args = args(TcpFrameArg::Tool);
        args.forward = 10.0;
        let body = move_tcp_body(&args);

        assert_eq!(&body[0..2], &300u16.to_le_bytes());
        assert_eq!(body[2], 1);
        assert_eq!(f32::from_le_bytes(body[3..7].try_into().unwrap()), 10.0);
        assert_eq!(f32::from_le_bytes(body[7..11].try_into().unwrap()), 0.0);
        assert_eq!(f32::from_le_bytes(body[11..15].try_into().unwrap()), 0.0);
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    let timeout = Duration::from_millis(cli.timeout_ms);
    let mut client = RuntimeClient::connect(&cli.url).await?;

    match cli.command {
        Command::Ping => {
            client.send_command(CMD_PING, &[]).await?;
            loop {
                match client.read_frame(timeout).await? {
                    RuntimeFrame::Pong => {
                        println!("pong");
                        break;
                    }
                    RuntimeFrame::Text(text) => println!("{text}"),
                    RuntimeFrame::Binary(payload) => {
                        println!("binary response: {} bytes", payload.len())
                    }
                    RuntimeFrame::Config(_) | RuntimeFrame::ArmState(_) => {}
                }
            }
        }
        Command::WsPing => {
            client.send_text("ping").await?;
            match client.read_frame(timeout).await? {
                RuntimeFrame::Text(text) => println!("{text}"),
                other => println!("{other:?}"),
            }
        }
        Command::Config(ConfigCommand::Get) => {
            client.send_command(CMD_CONFIG_GET, &[]).await?;
            print_config(wait_for_config(&mut client, timeout).await?);
        }
        Command::Config(ConfigCommand::Set(args)) => {
            let arm_ids = arm_servo_ids(args.arm_servo_ids)?;
            let body = [
                CONFIG_VERSION,
                args.steering_servo_id,
                arm_ids[0],
                arm_ids[1],
                arm_ids[2],
                arm_ids[3],
            ];
            client.send_command(CMD_CONFIG_SET, &body).await?;
            print_config(wait_for_config(&mut client, timeout).await?);
        }
        Command::Arm(ArmCommand::State) => {
            client.subscribe_arm_state(true).await?;
            print_arm_state(wait_for_arm_state(&mut client, timeout).await?);
        }
        Command::Arm(ArmCommand::Jog(args)) => {
            let mut body = vec![args.joint, args.direction as u8];
            push_u16_le(&mut body, args.speed);
            send_arm_command(&mut client, CMD_ARM_JOG, &body, "arm jog").await?;
            if let Some(duration_ms) = args.duration_ms {
                tokio::time::sleep(Duration::from_millis(duration_ms)).await;
                client
                    .send_command(CMD_ARM_STOP_JOINT, &[args.joint])
                    .await?;
                println!("sent arm stop joint {}", args.joint);
            }
        }
        Command::Arm(ArmCommand::Stop(args)) => {
            if let Some(joint) = args.joint {
                send_arm_command(&mut client, CMD_ARM_STOP_JOINT, &[joint], "arm stop joint")
                    .await?;
            } else {
                send_arm_command(&mut client, CMD_ARM_STOP, &[], "arm stop").await?;
            }
        }
        Command::Arm(ArmCommand::Hold(args)) => {
            let mut body = Vec::new();
            push_u16_le(&mut body, args.speed);
            send_arm_command(&mut client, CMD_ARM_HOLD, &body, "arm hold").await?;
        }
        Command::Arm(ArmCommand::GotoTicks(args)) => {
            let mut body = Vec::new();
            push_u16_le(&mut body, args.speed);
            for tick in args.ticks {
                push_i32_le(&mut body, tick);
            }
            send_arm_command(&mut client, CMD_ARM_GOTO_TICKS, &body, "arm goto ticks").await?;
        }
        Command::Arm(ArmCommand::GotoAngles(args)) => {
            let mut body = Vec::new();
            push_u16_le(&mut body, args.speed);
            for degrees in args.degrees {
                push_f32_le(&mut body, degrees);
            }
            send_arm_command(&mut client, CMD_ARM_GOTO_ANGLES, &body, "arm goto angles").await?;
        }
        Command::Arm(ArmCommand::GotoCoords(args)) => {
            let mut body = Vec::new();
            push_u16_le(&mut body, args.speed);
            push_f32_le(&mut body, args.x);
            push_f32_le(&mut body, args.y);
            push_f32_le(&mut body, args.z);
            send_arm_command(&mut client, CMD_ARM_GOTO_COORDS, &body, "arm goto coords").await?;
        }
        Command::Arm(ArmCommand::MoveTcp(args)) => {
            let body = move_tcp_body(&args);
            send_arm_command(&mut client, CMD_ARM_MOVE_RELATIVE, &body, "arm move tcp").await?;
        }
        Command::Arm(ArmCommand::SetJointTick(args)) => {
            let mut body = vec![args.joint];
            push_u16_le(&mut body, args.speed);
            push_i32_le(&mut body, args.tick);
            send_arm_command(
                &mut client,
                CMD_ARM_SET_JOINT_TICK,
                &body,
                "arm set joint tick",
            )
            .await?;
        }
        Command::Arm(ArmCommand::ClearFaults(args)) => {
            let joint = args.joint.unwrap_or(0xff);
            send_arm_command(
                &mut client,
                CMD_ARM_CLEAR_FAULTS,
                &[joint],
                "arm clear faults",
            )
            .await?;
        }
        Command::Arm(ArmCommand::ServoSet(args)) => {
            let mut body = vec![args.servo_id];
            push_u16_le(&mut body, args.angle_deg);
            push_u16_le(&mut body, args.duration_ms);
            send_arm_command(&mut client, CMD_SERVO_SET, &body, "servo set").await?;
        }
        Command::Drive(DriveCommand::Steer(args)) => {
            let body = [args.throttle as u8, args.steering as u8];
            send_arm_command(&mut client, CMD_DRIVE_STEER, &body, "drive steer").await?;
        }
        Command::Drive(DriveCommand::Stop) => {
            send_arm_command(&mut client, CMD_STOP_DRIVE, &[], "drive stop").await?;
        }
    }

    Ok(())
}
