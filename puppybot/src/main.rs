#![no_std]
#![no_main]

use embassy_executor::Spawner;

use embassy_net::{Runner, StackResources};
use embassy_time::{Duration, Timer};
use esp_alloc as _;
use esp_backtrace as _;
use esp_hal::{
    clock::CpuClock,
    gpio::{Level, Output, OutputConfig},
    interrupt::software::SoftwareInterruptControl,
    ram,
    rng::Rng,
    timer::timg::TimerGroup,
};
use esp_radio::wifi::{
    Config as WifiConfig, ControllerConfig, Interface, WifiController, sta::StationConfig,
};

mod mdns;
mod utility;
mod ws;

esp_bootloader_esp_idf::esp_app_desc!();

const WIFI_SSID: Option<&str> = option_env!("WIFI_SSID");
const WIFI_PASSWORD: Option<&str> = option_env!("WIFI_PASSWORD");

macro_rules! mk_static {
    ($t:ty, $val:expr) => {{
        static STATIC_CELL: static_cell::StaticCell<$t> = static_cell::StaticCell::new();
        STATIC_CELL.uninit().write($val)
    }};
}

#[esp_rtos::main]
async fn main(spawner: Spawner) -> ! {
    esp_println::logger::init_logger_from_env();
    esp_alloc::heap_allocator!(#[ram(reclaimed)] size: 64 * 1024);
    esp_alloc::heap_allocator!(size: 36 * 1024);

    let config = esp_hal::Config::default().with_cpu_clock(CpuClock::max());
    let peripherals = esp_hal::init(config);

    let status_led = Output::new(peripherals.GPIO2, Level::Low, OutputConfig::default());
    spawner.spawn(heartbeat(status_led).unwrap());

    let timg0 = TimerGroup::new(peripherals.TIMG0);
    let sw_int = SoftwareInterruptControl::new(peripherals.SW_INTERRUPT);
    esp_rtos::start(timg0.timer0, sw_int.software_interrupt0);

    log::info!("puppybot bare-metal firmware starting");

    let (ssid, password) = match (WIFI_SSID, WIFI_PASSWORD) {
        (Some(ssid), Some(password)) if !ssid.is_empty() => (ssid, password),
        _ => {
            log::warn!("Wi-Fi disabled; build with WIFI_SSID and WIFI_PASSWORD to connect");
            loop {
                Timer::after(Duration::from_secs(60)).await;
            }
        }
    };

    let station_config = WifiConfig::Station(
        StationConfig::default()
            .with_ssid(ssid)
            .with_password(password.into()),
    );

    log::info!("configuring Wi-Fi station for {ssid}");
    let (controller, interfaces) = esp_radio::wifi::new(
        peripherals.WIFI,
        ControllerConfig::default().with_initial_config(station_config),
    )
    .unwrap();

    let wifi_interface = interfaces.station;
    let network_config = embassy_net::Config::dhcpv4(Default::default());
    let rng = Rng::new();
    let seed = (rng.random() as u64) << 32 | rng.random() as u64;

    let (stack, runner) = embassy_net::new(
        wifi_interface,
        network_config,
        mk_static!(StackResources<8>, StackResources::<8>::new()),
        seed,
    );

    spawner.spawn(wifi_connection(controller).unwrap());
    spawner.spawn(net_task(runner).unwrap());

    stack.wait_config_up().await;

    if let Some(config) = stack.config_v4() {
        log::info!("Wi-Fi got IPv4 address {}", config.address);
        spawner.spawn(mdns::responder(stack, config.address.address()).unwrap());
        spawner.spawn(ws::http_websocket_server(stack).unwrap());
    }

    loop {
        Timer::after(Duration::from_secs(60)).await;
    }
}

#[embassy_executor::task]
async fn heartbeat(mut status_led: Output<'static>) {
    loop {
        status_led.toggle();
        log::info!("puppybot heartbeat");
        Timer::after(Duration::from_secs(1)).await;
    }
}

#[embassy_executor::task]
async fn wifi_connection(mut controller: WifiController<'static>) {
    loop {
        log::info!("connecting Wi-Fi station");

        match controller.connect_async().await {
            Ok(info) => {
                log::info!("Wi-Fi connected to {:?}", info);
                let disconnect = controller.wait_for_disconnect_async().await.ok();
                log::warn!("Wi-Fi disconnected: {:?}", disconnect);
            }
            Err(err) => {
                log::warn!("Wi-Fi connect failed: {:?}", err);
            }
        }

        Timer::after(Duration::from_secs(5)).await;
    }
}

#[embassy_executor::task]
async fn net_task(mut runner: Runner<'static, Interface<'static>>) {
    runner.run().await
}
