use std::net::SocketAddr;

const WGUI_ADDR: &str = "127.0.0.1:8081";

pub fn wgui_bind_addr() -> Result<SocketAddr, String> {
    let bind = std::env::var("PUPPYBOT_RUNTIME_UI_ADDR").unwrap_or_else(|_| WGUI_ADDR.to_string());
    bind.parse::<SocketAddr>()
        .map_err(|err| format!("invalid runtime UI bind address '{bind}': {err}"))
}
