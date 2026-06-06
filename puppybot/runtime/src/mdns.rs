use mdns_sd::{DaemonEvent, ServiceDaemon, ServiceInfo};

const SERVICE_TYPE: &str = "_ws._tcp.local.";
const INSTANCE_NAME: &str = "PuppyBot Runtime";
const HOST_NAME: &str = "puppybot-runtime.local.";

pub(crate) fn start_advertisement(port: u16) -> Option<ServiceDaemon> {
    let mdns = match ServiceDaemon::new() {
        Ok(mdns) => mdns,
        Err(err) => {
            log::warn!("failed to start mDNS daemon: {err}");
            return None;
        }
    };

    match mdns.monitor() {
        Ok(receiver) => {
            std::thread::spawn(move || {
                while let Ok(event) = receiver.recv() {
                    if let DaemonEvent::Error(err) = event {
                        log::warn!("mDNS daemon error: {err}");
                    }
                }
            });
        }
        Err(err) => log::warn!("failed to monitor mDNS daemon: {err}"),
    }

    let txt_properties = [("path", "/ws")];
    let service = match ServiceInfo::new(
        SERVICE_TYPE,
        INSTANCE_NAME,
        HOST_NAME,
        "",
        port,
        &txt_properties[..],
    ) {
        Ok(service) => service.enable_addr_auto(),
        Err(err) => {
            log::warn!("failed to build mDNS service info: {err}");
            return Some(mdns);
        }
    };

    if let Err(err) = mdns.register(service) {
        log::warn!("failed to register mDNS service: {err}");
    } else {
        log::info!(
            "advertising mDNS service {}.{} on port {}",
            INSTANCE_NAME,
            SERVICE_TYPE,
            port
        );
    }

    Some(mdns)
}
