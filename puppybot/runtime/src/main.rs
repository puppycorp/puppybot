use std::{net::SocketAddr, path::PathBuf};

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

#[tokio::main(flavor = "multi_thread")]
async fn main() {
    init_logger();
    let cli = Cli::parse();
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
