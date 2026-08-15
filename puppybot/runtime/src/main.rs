use std::{
    env as process_env,
    net::SocketAddr,
    path::{Path, PathBuf},
    process::Command as ProcessCommand,
};

use app::{App, AppOptions};
use clap::Parser;

mod app;
mod args;
mod capture;
mod config;
mod dc_motor_driver;
mod env;
mod http;
mod mdns;
mod sim;
mod stservo;

use args::{Cli, Command, DatasetCaptureArgs, RecordArgs};

const NVIDIA_DRIVER_VERSION_PATH: &str = "/proc/driver/nvidia/version";
const X11_RESTART_MARKER: &str = "PUPPYBOT_SIM_X11_RESTARTED";

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

fn should_restart_simulation_on_x11(cli: &Cli) -> bool {
    cfg!(target_os = "linux")
        && cli.command.is_none()
        && cli.run.simulated
        && !cli.run.headless
        && cli.run.screenshot.is_none()
        && process_env::var_os(X11_RESTART_MARKER).is_none()
        && process_env::var_os("WAYLAND_DISPLAY").is_some()
        && process_env::var_os("DISPLAY").is_some()
        && Path::new(NVIDIA_DRIVER_VERSION_PATH).is_file()
}

fn restart_simulation_on_x11(cli: &Cli) -> Result<(), String> {
    if !should_restart_simulation_on_x11(cli) {
        return Ok(());
    }

    log::warn!(
        "NVIDIA Wayland EGL detected; restarting simulation windows through X11 to avoid a native driver crash"
    );
    let status = ProcessCommand::new(
        process_env::current_exe()
            .map_err(|err| format!("resolve PuppyBot runtime executable: {err}"))?,
    )
    .args(process_env::args_os().skip(1))
    .env_remove("WAYLAND_DISPLAY")
    .env_remove("XDG_SESSION_TYPE")
    .env(X11_RESTART_MARKER, "1")
    .status()
    .map_err(|err| format!("restart PuppyBot simulation through X11: {err}"))?;
    std::process::exit(status.code().unwrap_or(1));
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
    let config_path = config::runtime_config_path(args.config.as_deref(), true);
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

async fn run_dataset_capture_command(args: DatasetCaptureArgs) -> Result<(), String> {
    let project_path = args
        .robotdreams_project
        .as_deref()
        .map(PathBuf::from)
        .unwrap_or_else(sim::SimulatedRuntimeBackend::default_project_path);
    let config_path = config::runtime_config_path(args.config.as_deref(), true);
    let config = config::load_runtime_config(&config_path)?.unwrap_or_default();
    let out = args
        .out
        .ok_or_else(|| "dataset-capture requires --out <DIRECTORY>".to_string())?;
    sim::capture_training_dataset_proof(
        &project_path,
        &config,
        &PathBuf::from(out),
        args.quick_grid,
    )
    .await
}

async fn run(cli: Cli) {
    let args = match cli.command {
        Some(Command::Record(args)) => {
            if let Err(err) = run_record_command(args).await {
                eprintln!("{err}");
                std::process::exit(1);
            }
            return;
        }
        Some(Command::DatasetCapture(args)) => {
            if let Err(err) = run_dataset_capture_command(args).await {
                eprintln!("{err}");
                std::process::exit(1);
            }
            return;
        }
        None => cli.run,
    };

    let screenshot = args.screenshot.clone();
    let screenshot_frames = args.frames.unwrap_or(120);
    if let Some(path) = screenshot {
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
        let config_path = config::runtime_config_path(args.config.as_deref(), true);
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
            args.debug_collider_overlay,
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
            eprintln!("{err}");
            std::process::exit(2);
        }
    };
    let options = AppOptions {
        config: args.config,
        servo_device: args.servo_device,
        simulated: args.simulated,
        robotdreams_project: args.robotdreams_project.map(PathBuf::from),
        debug_collision_overlay: args.debug_collider_overlay,
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

fn main() {
    init_logger();
    let cli = Cli::parse();
    if let Err(err) = restart_simulation_on_x11(&cli) {
        eprintln!("{err}");
        std::process::exit(1);
    }
    let runtime = match tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(err) => {
            eprintln!("failed to start PuppyBot runtime: {err}");
            std::process::exit(1);
        }
    };
    runtime.block_on(run(cli));
}
