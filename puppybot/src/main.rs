#![no_std]
#![no_main]

use esp_backtrace as _;
use esp_hal::{
    clock::CpuClock,
    delay::Delay,
    gpio::{Level, Output, OutputConfig},
    main,
};

esp_bootloader_esp_idf::esp_app_desc!();

#[main]
fn main() -> ! {
    esp_println::logger::init_logger_from_env();

    let config = esp_hal::Config::default().with_cpu_clock(CpuClock::max());
    let peripherals = esp_hal::init(config);

    let mut status_led = Output::new(peripherals.GPIO2, Level::Low, OutputConfig::default());
    let delay = Delay::new();

    log::info!("puppybot bare-metal firmware starting");

    loop {
        status_led.toggle();
        log::info!("puppybot heartbeat");
        delay.delay_millis(1_000);
    }
}
