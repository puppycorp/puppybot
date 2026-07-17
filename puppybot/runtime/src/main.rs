use std::{net::SocketAddr, path::PathBuf};

use app::{App, AppOptions};

mod app;
mod capture;
mod config;
mod dc_motor_driver;
mod env;
mod http;
mod mdns;
mod sim;
mod stservo;

#[derive(Debug, Default, PartialEq)]
struct RuntimeArgs {
    config: Option<String>,
    servo_device: Option<String>,
    simulated: bool,
    headless: bool,
    screenshot: Option<String>,
    state: Option<String>,
    state_frame: Option<usize>,
    frames: Option<u64>,
    camera: ScreenshotCameraOverrides,
    robotdreams_project: Option<String>,
    ui_bind: Option<String>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
struct ScreenshotCameraOverrides {
    target: Option<[f32; 3]>,
    radius_m: Option<f32>,
    azimuth_deg: Option<f32>,
    elevation_deg: Option<f32>,
}

impl ScreenshotCameraOverrides {
    fn is_customized(self) -> bool {
        self.target.is_some()
            || self.radius_m.is_some()
            || self.azimuth_deg.is_some()
            || self.elevation_deg.is_some()
    }

    fn resolve(self) -> sim::ScreenshotCamera {
        let defaults = sim::ScreenshotCamera::default();
        sim::ScreenshotCamera {
            target: self.target.unwrap_or(defaults.target),
            radius_m: self.radius_m.unwrap_or(defaults.radius_m),
            azimuth_deg: self.azimuth_deg.unwrap_or(defaults.azimuth_deg),
            elevation_deg: self.elevation_deg.unwrap_or(defaults.elevation_deg),
        }
    }
}

#[derive(Debug, Default, PartialEq, Eq)]
struct RecordArgs {
    config: Option<String>,
    simulated: bool,
    out: Option<String>,
    frames: Option<u32>,
    state: Option<String>,
    robotdreams_project: Option<String>,
}

#[derive(Debug, PartialEq)]
enum RuntimeCli {
    Run(RuntimeArgs),
    Record(RecordArgs),
    Help,
}

fn runtime_usage() -> &'static str {
    "Usage:\n  puppybot-runtime [OPTIONS]\n  puppybot-runtime record --sim --out <PATH.mp4> (--frames <N> | --state <TRACE.json>) [OPTIONS]\n\nRun options:\n  --config <PATH>               Load runtime config JSON, default ./puppybot.json\n  --servo-device <PATH>         Use an STServo serial device, overriding PUPPYBOT_STSERVO_PORT\n  --sim                         Run with in-process RobotDreams simulation and PGE preview\n  --headless                    Run --sim without a PGE preview window\n  --screenshot <PATH>           Render one real offscreen PGE frame and exit; requires --sim\n  --state <PATH>                Re-render a saved API/capture state without stepping simulation\n  --state-frame <INDEX>         Zero-based state frame to render, default 0\n  --frames <N>                  Simulation updates before screenshot, default 120\n  --camera-target <X,Y,Z>       Screenshot orbit target in meters\n  --camera-radius <M>           Screenshot orbit radius in meters, must be positive\n  --camera-azimuth <DEG>        Screenshot orbit azimuth in degrees\n  --camera-elevation <DEG>      Screenshot elevation, strictly between -90 and 90\n  --robotdreams-project <PATH>  RobotDreams project for --sim, default ../../robotdreams/project.json\n  --ui-bind <ADDR>              Bind the WGUI dashboard, default 127.0.0.1:8081\n\nRecord options:\n  --sim                         Record/replay RobotDreams simulation state (required)\n  --out <PATH.mp4>              Output H.264 MP4 path (required)\n  --frames <N>                  Number of live 50 fps frames to render\n  --state <TRACE.json>          Render an exact saved pose/camera trace without simulation stepping\n  --config <PATH>               Load runtime config JSON, default ./puppybot.json\n  --robotdreams-project <PATH>  RobotDreams project, default ../../robotdreams/project.json\n\n  -h, --help                    Show this help text"
}

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

fn parse_camera_azimuth(value: &str) -> Result<f32, String> {
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

fn parse_runtime_args<I, S>(args: I) -> Result<RuntimeCli, String>
where
    I: IntoIterator<Item = S>,
    S: Into<String>,
{
    let mut parsed = RuntimeArgs::default();
    let mut args = args.into_iter().map(Into::into).peekable();

    if args.peek().is_some_and(|arg| arg == "record") {
        let _ = args.next();
        return parse_record_args(args);
    }

    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-h" | "--help" => return Ok(RuntimeCli::Help),
            "--sim" => {
                parsed.simulated = true;
            }
            "--headless" => {
                parsed.headless = true;
            }
            "--screenshot" => {
                let Some(path) = args.next() else {
                    return Err("--screenshot requires a path".to_string());
                };
                let path = path.trim();
                if path.is_empty() {
                    return Err("--screenshot requires a non-empty path".to_string());
                }
                parsed.screenshot = Some(path.to_string());
            }
            "--frames" => {
                let Some(value) = args.next() else {
                    return Err("--frames requires a positive integer".to_string());
                };
                parsed.frames = Some(parse_frame_count(&value)?);
            }
            "--state" => {
                let path = args
                    .next()
                    .ok_or_else(|| "--state requires a JSON path".to_string())?;
                if path.trim().is_empty() {
                    return Err("--state requires a non-empty JSON path".to_string());
                }
                parsed.state = Some(path);
            }
            "--state-frame" => {
                let value = args
                    .next()
                    .ok_or_else(|| "--state-frame requires a non-negative integer".to_string())?;
                parsed.state_frame =
                    Some(value.parse::<usize>().map_err(|_| {
                        "--state-frame requires a non-negative integer".to_string()
                    })?);
            }
            "--camera-target" => {
                let value = args
                    .next()
                    .ok_or_else(|| "--camera-target requires X,Y,Z in meters".to_string())?;
                parsed.camera.target = Some(parse_camera_target(&value)?);
            }
            "--camera-radius" => {
                let value = args
                    .next()
                    .ok_or_else(|| "--camera-radius requires a positive number".to_string())?;
                parsed.camera.radius_m = Some(parse_camera_radius(&value)?);
            }
            "--camera-azimuth" => {
                let value = args
                    .next()
                    .ok_or_else(|| "--camera-azimuth requires a finite number".to_string())?;
                parsed.camera.azimuth_deg = Some(parse_camera_azimuth(&value)?);
            }
            "--camera-elevation" => {
                let value = args
                    .next()
                    .ok_or_else(|| "--camera-elevation requires a finite number".to_string())?;
                parsed.camera.elevation_deg = Some(parse_camera_elevation(&value)?);
            }
            "--config" => {
                let Some(path) = args.next() else {
                    return Err("--config requires a path".to_string());
                };
                let path = path.trim();
                if path.is_empty() {
                    return Err("--config requires a non-empty path".to_string());
                }
                parsed.config = Some(path.to_string());
            }
            "--servo-device" => {
                let Some(device) = args.next() else {
                    return Err("--servo-device requires a path".to_string());
                };
                let device = device.trim();
                if device.is_empty() {
                    return Err("--servo-device requires a non-empty path".to_string());
                }
                parsed.servo_device = Some(device.to_string());
            }
            "--ui-bind" => {
                let Some(bind) = args.next() else {
                    return Err("--ui-bind requires host:port".to_string());
                };
                let bind = bind.trim();
                if bind.is_empty() {
                    return Err("--ui-bind requires a non-empty host:port".to_string());
                }
                parsed.ui_bind = Some(bind.to_string());
            }
            "--robotdreams-project" => {
                let Some(path) = args.next() else {
                    return Err("--robotdreams-project requires a path".to_string());
                };
                let path = path.trim();
                if path.is_empty() {
                    return Err("--robotdreams-project requires a non-empty path".to_string());
                }
                parsed.robotdreams_project = Some(path.to_string());
            }
            _ => {
                if let Some(path) = arg.strip_prefix("--config=") {
                    let path = path.trim();
                    if path.is_empty() {
                        return Err("--config requires a non-empty path".to_string());
                    }
                    parsed.config = Some(path.to_string());
                } else if let Some(device) = arg.strip_prefix("--servo-device=") {
                    let device = device.trim();
                    if device.is_empty() {
                        return Err("--servo-device requires a non-empty path".to_string());
                    }
                    parsed.servo_device = Some(device.to_string());
                } else if let Some(bind) = arg.strip_prefix("--ui-bind=") {
                    let bind = bind.trim();
                    if bind.is_empty() {
                        return Err("--ui-bind requires a non-empty host:port".to_string());
                    }
                    parsed.ui_bind = Some(bind.to_string());
                } else if let Some(path) = arg.strip_prefix("--screenshot=") {
                    let path = path.trim();
                    if path.is_empty() {
                        return Err("--screenshot requires a non-empty path".to_string());
                    }
                    parsed.screenshot = Some(path.to_string());
                } else if let Some(value) = arg.strip_prefix("--frames=") {
                    parsed.frames = Some(parse_frame_count(value)?);
                } else if let Some(path) = arg.strip_prefix("--state=") {
                    if path.trim().is_empty() {
                        return Err("--state requires a non-empty JSON path".to_string());
                    }
                    parsed.state = Some(path.to_string());
                } else if let Some(value) = arg.strip_prefix("--state-frame=") {
                    parsed.state_frame = Some(value.parse::<usize>().map_err(|_| {
                        "--state-frame requires a non-negative integer".to_string()
                    })?);
                } else if let Some(value) = arg.strip_prefix("--camera-target=") {
                    parsed.camera.target = Some(parse_camera_target(value)?);
                } else if let Some(value) = arg.strip_prefix("--camera-radius=") {
                    parsed.camera.radius_m = Some(parse_camera_radius(value)?);
                } else if let Some(value) = arg.strip_prefix("--camera-azimuth=") {
                    parsed.camera.azimuth_deg = Some(parse_camera_azimuth(value)?);
                } else if let Some(value) = arg.strip_prefix("--camera-elevation=") {
                    parsed.camera.elevation_deg = Some(parse_camera_elevation(value)?);
                } else if let Some(path) = arg.strip_prefix("--robotdreams-project=") {
                    let path = path.trim();
                    if path.is_empty() {
                        return Err("--robotdreams-project requires a non-empty path".to_string());
                    }
                    parsed.robotdreams_project = Some(path.to_string());
                } else {
                    return Err(format!("unknown option: {arg}"));
                }
            }
        }
    }

    if parsed.headless && !parsed.simulated {
        return Err("--headless requires --sim".to_string());
    }
    if parsed.screenshot.is_some() && !parsed.simulated {
        return Err("--screenshot requires --sim".to_string());
    }
    if parsed.frames.is_some() && parsed.screenshot.is_none() {
        return Err("--frames requires --screenshot".to_string());
    }
    if parsed.camera.is_customized() && parsed.screenshot.is_none() {
        return Err("--camera-* options require --screenshot".to_string());
    }
    if parsed.state.is_some() && parsed.screenshot.is_none() {
        return Err("--state requires --screenshot".to_string());
    }
    if parsed.state_frame.is_some() && parsed.state.is_none() {
        return Err("--state-frame requires --state".to_string());
    }
    if parsed.state.is_some() && parsed.frames.is_some() {
        return Err("--frames cannot be combined with --state".to_string());
    }
    if parsed.state.is_some() && parsed.camera.is_customized() {
        return Err(
            "--camera-* cannot be combined with --state; saved camera is authoritative".to_string(),
        );
    }

    Ok(RuntimeCli::Run(parsed))
}

fn parse_record_args<I>(args: I) -> Result<RuntimeCli, String>
where
    I: IntoIterator<Item = String>,
{
    let mut parsed = RecordArgs::default();
    let mut args = args.into_iter();
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-h" | "--help" => return Ok(RuntimeCli::Help),
            "--sim" => parsed.simulated = true,
            "--out" => {
                let path = args
                    .next()
                    .ok_or_else(|| "--out requires an MP4 path".to_string())?;
                if path.trim().is_empty() {
                    return Err("--out requires a non-empty MP4 path".to_string());
                }
                parsed.out = Some(path);
            }
            "--frames" => {
                let value = args
                    .next()
                    .ok_or_else(|| "--frames requires a positive integer".to_string())?;
                let frames = parse_frame_count(&value)?;
                parsed.frames = Some(
                    u32::try_from(frames)
                        .map_err(|_| "--frames exceeds the supported maximum".to_string())?,
                );
            }
            "--state" => {
                let path = args
                    .next()
                    .ok_or_else(|| "--state requires a JSON path".to_string())?;
                if path.trim().is_empty() {
                    return Err("--state requires a non-empty JSON path".to_string());
                }
                parsed.state = Some(path);
            }
            "--config" => {
                let path = args
                    .next()
                    .ok_or_else(|| "--config requires a path".to_string())?;
                if path.trim().is_empty() {
                    return Err("--config requires a non-empty path".to_string());
                }
                parsed.config = Some(path);
            }
            "--robotdreams-project" => {
                let path = args
                    .next()
                    .ok_or_else(|| "--robotdreams-project requires a path".to_string())?;
                if path.trim().is_empty() {
                    return Err("--robotdreams-project requires a non-empty path".to_string());
                }
                parsed.robotdreams_project = Some(path);
            }
            _ => {
                if let Some(path) = arg.strip_prefix("--out=") {
                    if path.trim().is_empty() {
                        return Err("--out requires a non-empty MP4 path".to_string());
                    }
                    parsed.out = Some(path.to_string());
                } else if let Some(value) = arg.strip_prefix("--frames=") {
                    let frames = parse_frame_count(value)?;
                    parsed.frames = Some(
                        u32::try_from(frames)
                            .map_err(|_| "--frames exceeds the supported maximum".to_string())?,
                    );
                } else if let Some(path) = arg.strip_prefix("--state=") {
                    if path.trim().is_empty() {
                        return Err("--state requires a non-empty JSON path".to_string());
                    }
                    parsed.state = Some(path.to_string());
                } else if let Some(path) = arg.strip_prefix("--config=") {
                    if path.trim().is_empty() {
                        return Err("--config requires a non-empty path".to_string());
                    }
                    parsed.config = Some(path.to_string());
                } else if let Some(path) = arg.strip_prefix("--robotdreams-project=") {
                    if path.trim().is_empty() {
                        return Err("--robotdreams-project requires a non-empty path".to_string());
                    }
                    parsed.robotdreams_project = Some(path.to_string());
                } else {
                    return Err(format!("unknown record option: {arg}"));
                }
            }
        }
    }

    if !parsed.simulated {
        return Err("record requires --sim".to_string());
    }
    if parsed.out.is_none() {
        return Err("record requires --out <PATH.mp4>".to_string());
    }
    if parsed.frames.is_none() && parsed.state.is_none() {
        return Err("record requires --frames <N> or --state <TRACE.json>".to_string());
    }
    if parsed.frames.is_some() && parsed.state.is_some() {
        return Err("record --frames cannot be combined with --state".to_string());
    }
    Ok(RuntimeCli::Record(parsed))
}

fn parse_ui_bind(value: Option<&str>) -> Result<Option<SocketAddr>, String> {
    value
        .map(|bind| {
            bind.parse::<SocketAddr>()
                .map_err(|err| format!("invalid runtime UI bind address '{bind}': {err}"))
        })
        .transpose()
}

fn init_logger() {
    let _ = env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format_timestamp_millis()
        .try_init();
}

async fn run_record_command(args: RecordArgs) -> Result<(), String> {
    let project_path = args
        .robotdreams_project
        .as_deref()
        .map(PathBuf::from)
        .unwrap_or_else(sim::SimulatedRuntimeBackend::default_project_path);
    let out = args.out.expect("validated record output");
    if let Some(state_path) = args.state.as_deref() {
        let bytes = std::fs::read(state_path)
            .map_err(|err| format!("read capture trace {state_path}: {err}"))?;
        let trace = sim::parse_capture_trace_json(&bytes)?;
        sim::render_capture_trace_mp4(&project_path, &trace, &PathBuf::from(&out))?;
        println!(
            "saved pose-equivalent PuppyBot capture trace to {out}: {} frames at {} fps",
            trace.frames.len(),
            trace.fps
        );
        return Ok(());
    }
    let config_path = config::runtime_config_path(args.config.as_deref());
    let physical_config = config::load_runtime_config(&config_path)?.unwrap_or_default();
    let frames = args.frames.expect("validated record frame count");
    let delta_mm = sim::record_simulation_video(
        &project_path,
        &physical_config,
        &PathBuf::from(&out),
        frames,
    )
    .await?;
    println!(
        "saved PuppyBot simulation recording to {out}: {frames} frames at {} fps; controller/model TCP delta {delta_mm:.3} mm",
        sim::RECORDING_FPS
    );
    Ok(())
}

#[tokio::main(flavor = "multi_thread")]
async fn main() {
    init_logger();
    let args = match parse_runtime_args(std::env::args().skip(1)) {
        Ok(RuntimeCli::Run(args)) => args,
        Ok(RuntimeCli::Record(args)) => {
            if let Err(err) = run_record_command(args).await {
                eprintln!("{err}");
                std::process::exit(1);
            }
            return;
        }
        Ok(RuntimeCli::Help) => {
            println!("{}", runtime_usage());
            return;
        }
        Err(err) => {
            eprintln!("{err}\n\n{}", runtime_usage());
            std::process::exit(2);
        }
    };

    let screenshot = args.screenshot.clone();
    let screenshot_frames = args.frames.unwrap_or(120);
    if let Some(path) = screenshot {
        if args.servo_device.is_some() {
            eprintln!("--sim cannot be combined with --servo-device");
            std::process::exit(2);
        }
        let project_path = args
            .robotdreams_project
            .as_deref()
            .map(PathBuf::from)
            .unwrap_or_else(sim::SimulatedRuntimeBackend::default_project_path);
        if let Some(state_path) = args.state.as_deref() {
            let result = std::fs::read(state_path)
                .map_err(|err| format!("read capture state {state_path}: {err}"))
                .and_then(|bytes| sim::parse_capture_state_json(&bytes))
                .and_then(|state| {
                    sim::save_capture_state_screenshot(
                        &project_path,
                        &state,
                        args.state_frame.unwrap_or(0),
                        &PathBuf::from(&path),
                    )
                });
            match result {
                Ok(()) => {
                    println!(
                        "saved pose-equivalent PuppyBot capture-state frame {} to {path}",
                        args.state_frame.unwrap_or(0)
                    );
                    return;
                }
                Err(err) => {
                    eprintln!("{err}");
                    std::process::exit(1);
                }
            }
        }
        let config_path = config::runtime_config_path(args.config.as_deref());
        let physical_config = match config::load_runtime_config(&config_path) {
            Ok(config) => config.unwrap_or_default(),
            Err(err) => {
                eprintln!("{err}");
                std::process::exit(2);
            }
        };
        match sim::capture_simulation_screenshot(
            &project_path,
            &physical_config,
            &PathBuf::from(&path),
            screenshot_frames,
            args.camera.resolve(),
        )
        .await
        {
            Ok(delta_mm) => {
                println!(
                    "saved PuppyBot simulation screenshot to {path} after {screenshot_frames} frames; controller/model TCP delta {delta_mm:.3} mm"
                );
                return;
            }
            Err(err) => {
                eprintln!("{err}");
                std::process::exit(1);
            }
        }
    }

    let ui_bind = match parse_ui_bind(args.ui_bind.as_deref()) {
        Ok(bind) => bind,
        Err(err) => {
            eprintln!("{err}\n\n{}", runtime_usage());
            std::process::exit(2);
        }
    };
    let options = AppOptions {
        config: args.config,
        servo_device: args.servo_device,
        simulated: args.simulated,
        robotdreams_project: args.robotdreams_project.map(PathBuf::from),
        ui_bind,
        ws_bind: None,
    };

    let mut app = match App::with_options(options) {
        Ok(app) => app,
        Err(err) => {
            eprintln!("{err}");
            std::process::exit(2);
        }
    };

    if !args.headless {
        if let Some(preview) = app.simulated_preview() {
            let _app_thread = std::thread::spawn(move || {
                let runtime = match tokio::runtime::Builder::new_multi_thread()
                    .enable_all()
                    .build()
                {
                    Ok(runtime) => runtime,
                    Err(err) => {
                        eprintln!("failed to start PuppyBot runtime worker: {err}");
                        std::process::exit(1);
                    }
                };

                if let Err(err) = runtime.block_on(app.run()) {
                    eprintln!("{err}");
                    std::process::exit(1);
                }
                std::process::exit(0);
            });

            if let Err(err) = preview.run_blocking() {
                eprintln!("{err}");
                std::process::exit(1);
            }
            std::process::exit(0);
        }
    }

    if let Err(err) = app.run().await {
        eprintln!("{err}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_args_accept_help() {
        assert_eq!(parse_runtime_args(["--help"]), Ok(RuntimeCli::Help));
    }

    #[test]
    fn runtime_args_accept_options() {
        assert_eq!(
            parse_runtime_args([
                "--config",
                "custom.json",
                "--servo-device=/dev/ttyUSB0",
                "--ui-bind",
                "127.0.0.1:9000",
            ]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                config: Some("custom.json".to_string()),
                servo_device: Some("/dev/ttyUSB0".to_string()),
                simulated: false,
                headless: false,
                screenshot: None,
                state: None,
                state_frame: None,
                frames: None,
                camera: ScreenshotCameraOverrides::default(),
                robotdreams_project: None,
                ui_bind: Some("127.0.0.1:9000".to_string()),
            }))
        );
    }

    #[test]
    fn runtime_args_accept_simulation_options() {
        assert_eq!(
            parse_runtime_args(["--sim", "--robotdreams-project=robotdreams/project.json"]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                config: None,
                servo_device: None,
                simulated: true,
                headless: false,
                screenshot: None,
                state: None,
                state_frame: None,
                frames: None,
                camera: ScreenshotCameraOverrides::default(),
                robotdreams_project: Some("robotdreams/project.json".to_string()),
                ui_bind: None,
            }))
        );
    }

    #[test]
    fn runtime_args_accept_headless_simulation() {
        assert_eq!(
            parse_runtime_args(["--sim", "--headless"]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                config: None,
                servo_device: None,
                simulated: true,
                headless: true,
                screenshot: None,
                state: None,
                state_frame: None,
                frames: None,
                camera: ScreenshotCameraOverrides::default(),
                robotdreams_project: None,
                ui_bind: None,
            }))
        );
    }

    #[test]
    fn runtime_args_accept_finite_simulation_screenshot() {
        assert_eq!(
            parse_runtime_args([
                "--sim",
                "--screenshot",
                "workdir/screenshots/aligned.png",
                "--frames=80",
            ]),
            Ok(RuntimeCli::Run(RuntimeArgs {
                config: None,
                servo_device: None,
                simulated: true,
                headless: false,
                screenshot: Some("workdir/screenshots/aligned.png".to_string()),
                state: None,
                state_frame: None,
                frames: Some(80),
                camera: ScreenshotCameraOverrides::default(),
                robotdreams_project: None,
                ui_bind: None,
            }))
        );
    }

    #[test]
    fn runtime_args_accept_custom_screenshot_camera() {
        let RuntimeCli::Run(args) = parse_runtime_args([
            "--sim",
            "--screenshot=custom.png",
            "--camera-target",
            "0.1,-0.2,0.3",
            "--camera-radius=0.75",
            "--camera-azimuth",
            "450",
            "--camera-elevation=-25",
        ])
        .expect("parse custom screenshot camera") else {
            panic!("expected run command");
        };
        assert_eq!(args.camera.target, Some([0.1, -0.2, 0.3]));
        assert_eq!(args.camera.radius_m, Some(0.75));
        assert_eq!(args.camera.azimuth_deg, Some(90.0));
        assert_eq!(args.camera.elevation_deg, Some(-25.0));
    }

    #[test]
    fn runtime_args_reject_invalid_screenshot_camera() {
        assert_eq!(
            parse_runtime_args(["--camera-radius", "1"]),
            Err("--camera-* options require --screenshot".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--sim", "--screenshot", "x.png", "--camera-target", "1,2"]),
            Err("--camera-target requires X,Y,Z in meters".to_string())
        );
        assert_eq!(
            parse_runtime_args([
                "--sim",
                "--screenshot",
                "x.png",
                "--camera-target",
                "1,NaN,3"
            ]),
            Err("--camera-target requires a finite number".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--sim", "--screenshot", "x.png", "--camera-radius", "0"]),
            Err("--camera-radius must be positive".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--sim", "--screenshot", "x.png", "--camera-azimuth", "inf"]),
            Err("--camera-azimuth requires a finite number".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--sim", "--screenshot", "x.png", "--camera-elevation", "90"]),
            Err("--camera-elevation must be strictly between -90 and 90 degrees".to_string())
        );
    }

    #[test]
    fn camera_azimuth_normalization_handles_large_finite_values() {
        let normalized = parse_camera_azimuth("3.4028235e38").expect("normalize finite f32");
        assert!(normalized.is_finite());
        assert!((-180.0..180.0).contains(&normalized));
    }

    #[test]
    fn runtime_args_accept_finite_simulation_recording() {
        assert_eq!(
            parse_runtime_args([
                "record",
                "--sim",
                "--out",
                "workdir/recordings/aligned.mp4",
                "--frames=150",
                "--robotdreams-project",
                "robotdreams/project.json",
            ]),
            Ok(RuntimeCli::Record(RecordArgs {
                config: None,
                simulated: true,
                out: Some("workdir/recordings/aligned.mp4".to_string()),
                frames: Some(150),
                state: None,
                robotdreams_project: Some("robotdreams/project.json".to_string()),
            }))
        );
    }

    #[test]
    fn runtime_args_accept_state_replay_for_screenshot_and_record() {
        let screenshot = parse_runtime_args([
            "--sim",
            "--screenshot",
            "replay.png",
            "--state",
            "state.json",
            "--state-frame=2",
        ])
        .expect("parse screenshot state replay");
        let RuntimeCli::Run(screenshot) = screenshot else {
            panic!("expected run command");
        };
        assert_eq!(screenshot.state.as_deref(), Some("state.json"));
        assert_eq!(screenshot.state_frame, Some(2));

        for args in [
            vec![
                "record",
                "--sim",
                "--out",
                "replay.mp4",
                "--state",
                "trace.json",
            ],
            vec!["record", "--sim", "--out=replay.mp4", "--state=trace.json"],
        ] {
            let RuntimeCli::Record(record) =
                parse_runtime_args(args).expect("parse record state replay")
            else {
                panic!("expected record command");
            };
            assert_eq!(record.state.as_deref(), Some("trace.json"));
            assert_eq!(record.frames, None);
        }
    }

    #[test]
    fn runtime_args_reject_state_replay_conflicts() {
        assert_eq!(
            parse_runtime_args([
                "record",
                "--sim",
                "--out",
                "replay.mp4",
                "--state",
                "trace.json",
                "--frames",
                "10",
            ]),
            Err("record --frames cannot be combined with --state".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--sim", "--state", "state.json"]),
            Err("--state requires --screenshot".to_string())
        );
    }

    #[test]
    fn runtime_args_reject_incomplete_recording() {
        assert_eq!(
            parse_runtime_args(["record", "--out", "aligned.mp4", "--frames", "10"]),
            Err("record requires --sim".to_string())
        );
        assert_eq!(
            parse_runtime_args(["record", "--sim", "--frames", "10"]),
            Err("record requires --out <PATH.mp4>".to_string())
        );
        assert_eq!(
            parse_runtime_args(["record", "--sim", "--out", "aligned.mp4"]),
            Err("record requires --frames <N> or --state <TRACE.json>".to_string())
        );
    }

    #[test]
    fn runtime_args_reject_missing_values() {
        assert_eq!(
            parse_runtime_args(["--servo-device"]),
            Err("--servo-device requires a path".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--config="]),
            Err("--config requires a non-empty path".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--robotdreams-project"]),
            Err("--robotdreams-project requires a path".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--headless"]),
            Err("--headless requires --sim".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--screenshot", "frame.png"]),
            Err("--screenshot requires --sim".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--frames", "12"]),
            Err("--frames requires --screenshot".to_string())
        );
        assert_eq!(
            parse_runtime_args(["--sim", "--screenshot", "frame.png", "--frames", "0"]),
            Err("--frames requires a positive integer".to_string())
        );
    }
}
