use clap::{Args, Parser, Subcommand};

use crate::sim;

fn parse_finite_f32(flag: &str, value: &str) -> Result<f32, String> {
    let parsed = value
        .trim()
        .parse::<f32>()
        .map_err(|_| format!("{flag} requires a finite number"))?;
    if !parsed.is_finite() {
        return Err(format!("{flag} requires a finite number"));
    }
    Ok(parsed)
}

fn parse_camera_target(value: &str) -> Result<[f32; 3], String> {
    let values = value.split(',').collect::<Vec<_>>();
    if values.len() != 3 {
        return Err("--camera-target requires X,Y,Z in meters".to_string());
    }
    Ok([
        parse_finite_f32("--camera-target", values[0])?,
        parse_finite_f32("--camera-target", values[1])?,
        parse_finite_f32("--camera-target", values[2])?,
    ])
}

fn parse_camera_radius(value: &str) -> Result<f32, String> {
    let radius = parse_finite_f32("--camera-radius", value)?;
    if radius <= 0.0 {
        return Err("--camera-radius must be positive".to_string());
    }
    Ok(radius)
}

pub(crate) fn parse_camera_azimuth(value: &str) -> Result<f32, String> {
    let degrees = parse_finite_f32("--camera-azimuth", value)?;
    let normalized = degrees.rem_euclid(360.0);
    Ok(if normalized >= 180.0 {
        normalized - 360.0
    } else {
        normalized
    })
}

fn parse_camera_elevation(value: &str) -> Result<f32, String> {
    let degrees = parse_finite_f32("--camera-elevation", value)?;
    if degrees <= -90.0 || degrees >= 90.0 {
        return Err("--camera-elevation must be strictly between -90 and 90 degrees".to_string());
    }
    Ok(degrees)
}

fn parse_frame_count(value: &str) -> Result<u64, String> {
    let frames = value
        .trim()
        .parse::<u64>()
        .map_err(|_| "--frames requires a positive integer".to_string())?;
    if frames == 0 {
        return Err("--frames requires a positive integer".to_string());
    }
    Ok(frames)
}

fn parse_record_frame_count(value: &str) -> Result<u32, String> {
    let frames = parse_frame_count(value)?;
    u32::try_from(frames).map_err(|_| "--frames exceeds the supported maximum".to_string())
}

fn parse_state_frame(value: &str) -> Result<usize, String> {
    value
        .trim()
        .parse::<usize>()
        .map_err(|_| "--state-frame requires a non-negative integer".to_string())
}

fn non_empty_path(value: &str, message: &str) -> Result<String, String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err(message.to_string());
    }
    Ok(trimmed.to_string())
}

fn parse_config(value: &str) -> Result<String, String> {
    non_empty_path(value, "--config requires a non-empty path")
}

fn parse_servo_device(value: &str) -> Result<String, String> {
    non_empty_path(value, "--servo-device requires a non-empty path")
}

fn parse_screenshot_path(value: &str) -> Result<String, String> {
    non_empty_path(value, "--screenshot requires a non-empty path")
}

fn parse_state_path(value: &str) -> Result<String, String> {
    non_empty_path(value, "--state requires a non-empty JSON path")
}

fn parse_ui_bind(value: &str) -> Result<String, String> {
    non_empty_path(value, "--ui-bind requires a non-empty host:port")
}

fn parse_robotdreams_project(value: &str) -> Result<String, String> {
    non_empty_path(value, "--robotdreams-project requires a non-empty path")
}

fn parse_out(value: &str) -> Result<String, String> {
    non_empty_path(value, "--out requires a non-empty MP4 path")
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Args)]
pub struct ScreenshotCameraOverrides {
    #[arg(long = "camera-target", value_parser = parse_camera_target, requires = "screenshot", conflicts_with = "state")]
    pub target: Option<[f32; 3]>,
    #[arg(long = "camera-radius", value_parser = parse_camera_radius, requires = "screenshot", conflicts_with = "state")]
    pub radius_m: Option<f32>,
    #[arg(long = "camera-azimuth", value_parser = parse_camera_azimuth, requires = "screenshot", conflicts_with = "state")]
    pub azimuth_deg: Option<f32>,
    #[arg(long = "camera-elevation", value_parser = parse_camera_elevation, requires = "screenshot", conflicts_with = "state")]
    pub elevation_deg: Option<f32>,
}

impl ScreenshotCameraOverrides {
    pub fn resolve(self) -> sim::ScreenshotCamera {
        let defaults = sim::ScreenshotCamera::default();
        sim::ScreenshotCamera {
            target: self.target.unwrap_or(defaults.target),
            radius_m: self.radius_m.unwrap_or(defaults.radius_m),
            azimuth_deg: self.azimuth_deg.unwrap_or(defaults.azimuth_deg),
            elevation_deg: self.elevation_deg.unwrap_or(defaults.elevation_deg),
        }
    }
}

#[derive(Debug, Default, PartialEq, Args)]
pub struct RuntimeArgs {
    #[arg(long, value_parser = parse_config)]
    pub config: Option<String>,
    #[arg(long = "servo-device", value_parser = parse_servo_device, conflicts_with = "simulated")]
    pub servo_device: Option<String>,
    #[arg(long = "sim")]
    pub simulated: bool,
    #[arg(long, requires = "simulated")]
    pub headless: bool,
    #[arg(long = "debug-collider-overlay", requires = "simulated")]
    pub debug_collider_overlay: bool,
    #[arg(long, value_parser = parse_screenshot_path, requires = "simulated", conflicts_with = "servo_device")]
    pub screenshot: Option<String>,
    #[arg(long, value_parser = parse_state_path, requires = "screenshot")]
    pub state: Option<String>,
    #[arg(long = "state-frame", value_parser = parse_state_frame, requires = "state")]
    pub state_frame: Option<usize>,
    #[arg(long, value_parser = parse_frame_count, requires = "screenshot", conflicts_with = "state")]
    pub frames: Option<u64>,
    #[arg(long = "robotdreams-project", value_parser = parse_robotdreams_project)]
    pub robotdreams_project: Option<String>,
    #[arg(long = "ui-bind", value_parser = parse_ui_bind)]
    pub ui_bind: Option<String>,
    #[command(flatten)]
    pub camera: ScreenshotCameraOverrides,
}

#[derive(Debug, Default, PartialEq, Eq, Args)]
pub struct RecordArgs {
    #[arg(long, value_parser = parse_config)]
    pub config: Option<String>,
    #[arg(long = "sim", required = true)]
    pub simulated: bool,
    #[arg(long, value_parser = parse_out, required = true)]
    pub out: Option<String>,
    #[arg(long, value_parser = parse_record_frame_count, conflicts_with = "state")]
    pub frames: Option<u32>,
    #[arg(long, value_parser = parse_state_path)]
    pub state: Option<String>,
    #[arg(long = "robotdreams-project", value_parser = parse_robotdreams_project)]
    pub robotdreams_project: Option<String>,
}

#[derive(Debug, Default, PartialEq, Eq, Args)]
pub struct DatasetCaptureArgs {
    #[arg(long, value_parser = parse_config)]
    pub config: Option<String>,
    #[arg(long = "sim", required = true)]
    pub simulated: bool,
    #[arg(long, value_parser = parse_out, required = true)]
    pub out: Option<String>,
    #[arg(long = "quick-grid")]
    pub quick_grid: bool,
    #[arg(long = "robotdreams-project", value_parser = parse_robotdreams_project)]
    pub robotdreams_project: Option<String>,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    Record(RecordArgs),
    DatasetCapture(DatasetCaptureArgs),
}

#[derive(Debug, Parser)]
#[command(name = "puppybot-runtime")]
pub struct Cli {
    #[command(flatten)]
    pub run: RuntimeArgs,
    #[command(subcommand)]
    pub command: Option<Command>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn camera_azimuth_normalization_handles_large_finite_values() {
        let normalized = parse_camera_azimuth("3.4028235e38").expect("normalize finite f32");
        assert!(normalized.is_finite());
        assert!((-180.0..180.0).contains(&normalized));
    }

    #[test]
    fn run_args_reject_invalid_screenshot_camera() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "--sim", "--screenshot", "x.png", "--camera-target", "1,2"]).is_err());
        assert!(Cli::try_parse_from(["puppybot-runtime", "--sim", "--screenshot", "x.png", "--camera-target", "1,NaN,3"]).is_err());
        assert!(Cli::try_parse_from(["puppybot-runtime", "--sim", "--screenshot", "x.png", "--camera-radius", "0"]).is_err());
        assert!(Cli::try_parse_from(["puppybot-runtime", "--sim", "--screenshot", "x.png", "--camera-azimuth", "inf"]).is_err());
        assert!(Cli::try_parse_from(["puppybot-runtime", "--sim", "--screenshot", "x.png", "--camera-elevation", "90"]).is_err());
    }

    #[test]
    fn run_args_parse_custom_screenshot_camera() {
        let cli = Cli::try_parse_from([
            "puppybot-runtime",
            "--sim",
            "--screenshot=custom.png",
            "--camera-target",
            "0.1,-0.2,0.3",
            "--camera-radius=0.75",
            "--camera-azimuth",
            "450",
            "--camera-elevation=-25",
        ])
        .expect("parse custom screenshot camera");
        assert_eq!(cli.run.camera.target, Some([0.1, -0.2, 0.3]));
        assert_eq!(cli.run.camera.radius_m, Some(0.75));
        assert_eq!(cli.run.camera.azimuth_deg, Some(90.0));
        assert_eq!(cli.run.camera.elevation_deg, Some(-25.0));
    }

    #[test]
    fn run_args_reject_empty_config_path() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "--config="]).is_err());
    }

    #[test]
    fn run_args_reject_zero_frame_count() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "--sim", "--screenshot", "frame.png", "--frames", "0"]).is_err());
    }

    #[test]
    fn run_args_parse_state_frame() {
        let cli = Cli::try_parse_from([
            "puppybot-runtime",
            "--sim",
            "--screenshot",
            "replay.png",
            "--state",
            "state.json",
            "--state-frame=2",
        ])
        .expect("parse screenshot state replay");
        assert_eq!(cli.run.state.as_deref(), Some("state.json"));
        assert_eq!(cli.run.state_frame, Some(2));
    }

    #[test]
    fn run_args_require_sim_for_headless() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "--headless"]).is_err());
    }

    #[test]
    fn run_args_require_sim_for_screenshot() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "--screenshot", "x.png"]).is_err());
    }

    #[test]
    fn run_args_require_screenshot_for_frames() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "--frames", "12"]).is_err());
    }

    #[test]
    fn run_args_require_screenshot_for_camera_overrides() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "--camera-radius", "1"]).is_err());
    }

    #[test]
    fn run_args_reject_frames_with_state() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "--sim", "--screenshot", "x.png", "--state", "state.json", "--frames", "10"]).is_err());
    }

    #[test]
    fn run_args_reject_camera_overrides_with_state() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "--sim", "--screenshot", "x.png", "--state", "state.json", "--camera-radius", "1.0"]).is_err());
    }

    #[test]
    fn record_requires_out() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "record", "--sim", "--frames", "10"]).is_err());
    }

    #[test]
    fn record_requires_sim() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "record", "--out", "x.mp4", "--frames", "10"]).is_err());
    }

    #[test]
    fn record_rejects_frames_with_state() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "record", "--sim", "--out", "x.mp4", "--state", "trace.json", "--frames", "10"]).is_err());
    }

    #[test]
    fn record_rejects_quick_grid() {
        assert!(Cli::try_parse_from(["puppybot-runtime", "record", "--sim", "--out", "x.mp4", "--frames", "10", "--quick-grid"]).is_err());
    }

    #[test]
    fn dataset_capture_parses_quick_grid() {
        let cli = Cli::try_parse_from(["puppybot-runtime", "dataset-capture", "--sim", "--out", "dataset/", "--quick-grid"])
            .expect("parse dataset capture");
        let Command::DatasetCapture(args) = cli.command.expect("dataset-capture command") else {
            panic!("expected dataset-capture");
        };
        assert!(args.quick_grid);
    }

    #[test]
    fn record_round_trip() {
        let cli = Cli::try_parse_from([
            "puppybot-runtime",
            "record",
            "--sim",
            "--out",
            "workdir/recordings/aligned.mp4",
            "--frames=150",
            "--robotdreams-project",
            "robotdreams/project.json",
        ])
        .expect("parse record");
        let Command::Record(args) = cli.command.expect("record command") else {
            panic!("expected record");
        };
        assert!(args.simulated);
        assert_eq!(args.out.as_deref(), Some("workdir/recordings/aligned.mp4"));
        assert_eq!(args.frames, Some(150));
        assert_eq!(args.robotdreams_project.as_deref(), Some("robotdreams/project.json"));
        assert_eq!(args.state, None);
    }
}