// Classic ESP32, ESP-IDF v5.5.1 soc/{uart_reg,dport_reg,gpio_sig_map}.h.
// CPU/APB clocks retain ROM defaults; UARTs explicitly use the 80 MHz APB.
// Single owner, polled I/O. No blocking FIFO loops or Linux syscalls.
import "../../../flexscript/lib/platform/esp32-common.flex";

fn pe_uart_base(bus) { if bus == 0 { return 0x3ff40000; } if bus == 2 { return 0x3ff6e000; } return -22; }
fn pe_uart_reset(bus) {
    let base = pe_uart_base(bus); if base < 0 { return base; }
    let value = esp32_load32(base + 32); esp32_store32(base + 32, value | (3 << 17));
    esp32_store32(base + 32, value & ~(3 << 17)); esp32_store32(base + 16, 0x1ffff); return 0;
}
fn pe_uart_init(bus, baud) {
    let base = pe_uart_base(bus); if base < 0 || (baud != 115200 && baud != 1000000) { return -22; }
    if bus == 2 { esp_clock_enable(0, 23); esp_gpio_write(17, 1); esp_gpio_open_drain(17, 0); esp_gpio_route_output(17, 198); esp_gpio_input(16, 1); esp_gpio_route_input(16, 198); }
    esp32_store32(base + 12, 0); let divider = 1280000000 / baud;
    esp32_store32(base + 20, (divider >> 4) | ((divider & 15) << 20));
    esp32_store32(base + 32, (1 << 27) | (3 << 2) | (1 << 4));
    esp32_store32(base + 36, 0); esp32_store32(base + 64, 0); esp32_store32(base + 68, 0); return pe_uart_reset(bus);
}
fn pe_uart_read(bus) {
    let base = pe_uart_base(bus); if base < 0 { return base; }
    // ESP32 erratum 3.21: mask interrupts around FIFO reads; count is 8 bits.
    let ps = esp32_irq_save(); let result = -1;
    if esp32_load32(base + 4) & 28 { pe_uart_reset(bus); result = -5; }
    else if esp32_load32(base + 28) & 255 { result = esp32_load32(base) & 255; }
    esp32_irq_restore(ps); return result;
}
fn pe_uart_write(bus, data, size) {
    let base = pe_uart_base(bus); if base < 0 || size < 0 || size > 2048 { return -22; }
    let room = 126 - ((esp32_load32(base + 28) >> 16) & 255); let n = 0;
    while n < size && n < room { esp32_store32(base, load8(data + n)); n = n + 1; } return n;
}
fn pe_uart_idle(bus) { let base = pe_uart_base(bus); if base < 0 { return 0; } return !(esp32_load32(base + 28) & 0x0fff0000); }
