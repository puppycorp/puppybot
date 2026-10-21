use std::{
    env as process_env,
    ffi::OsStr,
    fs::{self, File, OpenOptions},
    io::{self, Write},
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
const DEFAULT_RUNTIME_LOG_PATH: &str = "logs.txt";
const RUNTIME_LOG_ENV: &str = "PUPPYBOT_RUNTIME_LOG";
const VERBOSE_LOG_ENV: &str = "LOG";
const X11_RESTART_MARKER: &str = "PUPPYBOT_SIM_X11_RESTARTED";

struct TerminalAndFileWriter {
    file: File,
}

impl Write for TerminalAndFileWriter {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        io::stderr().write_all(buffer)?;
        self.file.write_all(buffer)?;
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        io::stderr().flush()?;
        self.file.flush()
    }
}

fn parse_ui_bind(value: Option<&str>) -> Result<Option<SocketAddr>, String> {
    value
        .map(|bind| {
            bind.parse::<SocketAddr>()
                .map_err(|err| format!("invalid runtime UI bind address '{bind}': {err}"))
        })
        .transpose()
}

fn runtime_log_path(cli_path: Option<&str>, env_path: Option<&OsStr>) -> PathBuf {
    cli_path
        .map(PathBuf::from)
        .or_else(|| env_path.filter(|path| !path.is_empty()).map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from(DEFAULT_RUNTIME_LOG_PATH))
}

fn verbose_logging_enabled(value: Option<&OsStr>) -> bool {
    let Some(value) = value else {
        return false;
    };
    if value.is_empty() {
        return false;
    }
    !value.to_str().is_some_and(|value| {
        value == "0"
            || value.eq_ignore_ascii_case("false")
            || value.eq_ignore_ascii_case("no")
            || value.eq_ignore_ascii_case("off")
    })
}

fn init_logger(log_file: Option<&Path>, verbose: bool) -> Result<(), String> {
    let default_filter = if verbose {
        "info,puppybot_core::robot=debug"
    } else {
        "info"
    };
    let mut builder =
        env_logger::Builder::from_env(env_logger::Env::default().default_filter_or(default_filter));
    builder.format_timestamp_millis();
    if let Some(path) = log_file {
        if let Some(parent) = path.parent()
            && !parent.as_os_str().is_empty()
        {
            fs::create_dir_all(parent)
                .map_err(|err| format!("create log directory {}: {err}", parent.display()))?;
        }
        let file = OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .open(path)
            .map_err(|err| format!("open runtime log {}: {err}", path.display()))?;
        builder.target(env_logger::Target::Pipe(Box::new(TerminalAndFileWriter {
            file,
        })));
    }
    builder.try_init().map_err(|err| err.to_string())
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
    let cli = Cli::parse();
    let env_log_file = process_env::var_os(RUNTIME_LOG_ENV);
    let log_file = runtime_log_path(cli.log_file.as_deref(), env_log_file.as_deref());
    let verbose_log_value = process_env::var_os(VERBOSE_LOG_ENV);
    let verbose_logging = verbose_logging_enabled(verbose_log_value.as_deref());
    if let Err(err) = init_logger(Some(&log_file), verbose_logging) {
        eprintln!("failed to initialize runtime logging: {err}");
        std::process::exit(2);
    }
    log::info!("writing runtime logs to {}", log_file.display());
    if verbose_logging {
        log::info!("verbose gripper feedback logging enabled by {VERBOSE_LOG_ENV}");
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_log_path_defaults_to_logs_txt() {
        assert_eq!(runtime_log_path(None, None), PathBuf::from("logs.txt"));
        assert_eq!(
            runtime_log_path(None, Some(OsStr::new(""))),
            PathBuf::from("logs.txt")
        );
    }

    #[test]
    fn runtime_log_path_prefers_cli_then_environment() {
        assert_eq!(
            runtime_log_path(None, Some(OsStr::new("environment.log"))),
            PathBuf::from("environment.log")
        );
        assert_eq!(
            runtime_log_path(
                Some("command-line.log"),
                Some(OsStr::new("environment.log"))
            ),
            PathBuf::from("command-line.log")
        );
    }

    #[test]
    fn verbose_logging_requires_a_truthy_log_value() {
        assert!(!verbose_logging_enabled(None));
        for value in ["", "0", "false", "FALSE", "no", "off"] {
            assert!(!verbose_logging_enabled(Some(OsStr::new(value))), "{value}");
        }
        for value in ["1", "true", "yes", "on", "debug"] {
            assert!(verbose_logging_enabled(Some(OsStr::new(value))), "{value}");
        }
    }
}
