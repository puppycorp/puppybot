use std::net::SocketAddr;

use app::{App, AppOptions};

mod app;
mod config;
mod dc_motor_driver;
mod env;
mod mdns;
mod stservo;
mod ws;

#[derive(Debug, Default, PartialEq, Eq)]
struct RuntimeArgs {
    config: Option<String>,
    servo_device: Option<String>,
    ui_bind: Option<String>,
}

#[derive(Debug, PartialEq, Eq)]
enum RuntimeCli {
    Run(RuntimeArgs),
    Help,
}

fn runtime_usage() -> &'static str {
    "Usage: puppybot-runtime [OPTIONS]\n\nOptions:\n  --config <PATH>        Load runtime config JSON, default ./puppybot.json\n  --servo-device <PATH>  Use an STServo serial device, overriding PUPPYBOT_STSERVO_PORT\n  --ui-bind <ADDR>       Bind the WGUI dashboard, default 127.0.0.1:8081\n  -h, --help             Show this help text"
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
                } else {
                    return Err(format!("unknown option: {arg}"));
                }
            }
        }
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
                ui_bind: Some("127.0.0.1:9000".to_string()),
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
    }
}
