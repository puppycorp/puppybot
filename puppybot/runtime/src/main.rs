use std::{net::SocketAddr, path::PathBuf};

use app::{App, AppOptions};

mod app;
mod config;
mod dc_motor_driver;
mod env;
mod http;
mod mdns;
mod sim;
mod stservo;

#[derive(Debug, Default, PartialEq, Eq)]
struct RuntimeArgs {
    config: Option<String>,
    servo_device: Option<String>,
    simulated: bool,
    headless: bool,
    robotdreams_project: Option<String>,
    ui_bind: Option<String>,
}

#[derive(Debug, PartialEq, Eq)]
enum RuntimeCli {
    Run(RuntimeArgs),
    Help,
}

fn runtime_usage() -> &'static str {
    "Usage: puppybot-runtime [OPTIONS]\n\nOptions:\n  --config <PATH>               Load runtime config JSON, default ./puppybot.json\n  --servo-device <PATH>         Use an STServo serial device, overriding PUPPYBOT_STSERVO_PORT\n  --sim                         Run with in-process RobotDreams simulation and PGE preview\n  --headless                    Run --sim without a PGE preview window\n  --robotdreams-project <PATH>  RobotDreams project for --sim, default ../../robotdreams/project.json\n  --ui-bind <ADDR>              Bind the WGUI dashboard, default 127.0.0.1:8081\n  -h, --help                    Show this help text"
}

fn parse_runtime_args<I, S>(args: I) -> Result<RuntimeCli, String>
where
    I: IntoIterator<Item = S>,
    S: Into<String>,
{
    let mut parsed = RuntimeArgs::default();
    let mut args = args.into_iter().map(Into::into);

    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-h" | "--help" => return Ok(RuntimeCli::Help),
            "--sim" => {
                parsed.simulated = true;
            }
            "--headless" => {
                parsed.headless = true;
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

    Ok(RuntimeCli::Run(parsed))
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

#[tokio::main(flavor = "multi_thread")]
async fn main() {
    init_logger();
    let args = match parse_runtime_args(std::env::args().skip(1)) {
        Ok(RuntimeCli::Run(args)) => args,
        Ok(RuntimeCli::Help) => {
            println!("{}", runtime_usage());
            return;
        }
        Err(err) => {
            eprintln!("{err}\n\n{}", runtime_usage());
            std::process::exit(2);
        }
    };

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
                robotdreams_project: None,
                ui_bind: None,
            }))
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
    }
}
