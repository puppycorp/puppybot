// Classic ESP32-WROOM/LX6 only. Single CPU, ROM-default APB, no radio runtime.
import "../vendor/esp32-xip.flex";
import "../../../flexscript/lib/platform/esp32-timer.flex";
import "uart.flex";
import "controller.flex";

fn pe_now_us() { return esp_timer_read(0); }
fn main() {
    if esp_timer_init(0, 80, 0) || esp_timer_start(0) || pe_uart_init(0, 115200) || pe_uart_init(2, 1000000) { return 1; }
    if pf_init() { return 2; } pf_status();
    while 1 { pf_poll(); }
    return 0;
}
