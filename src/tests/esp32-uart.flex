// Register/interrupt regression for the production UART0/2 adapter.
// Expected fields from ESP-IDF v5.5.1 classic ESP32 uart_reg.h/gpio_sig_map.h.
import "../firmware/uart.flex";
global pu_registers = 0;
global pu_count = 0;
global pu_mask = 0;
global pu_fault = 0;
global pu_reads = 0;
global pu_writes = 0;
fn pu_slot(address) {
    let i = 0; while i < pu_count { if load64(pu_registers + i * 16) == address { return pu_registers + i * 16 + 8; } i = i + 1; }
    store64(pu_registers + i * 16, address); pu_count = pu_count + 1; return pu_registers + i * 16 + 8;
}
fn esp32_load32(address) {
    if address == 0x3ff40000 || address == 0x3ff6e000 { pu_reads = pu_reads + 1; if !pu_mask { pu_fault = 1; } }
    return load64(pu_slot(address));
}
fn esp32_store32(address, value) { store64(pu_slot(address), value & 0xffffffff); if address == 0x3ff40000 || address == 0x3ff6e000 { pu_writes = pu_writes + 1; } return 0; }
fn esp32_irq_save() { let old = pu_mask; pu_mask = 15; return old; }
fn esp32_irq_restore(mask) { pu_mask = mask; return 0; }
fn esp32_cycles() { return 0; }
fn main() {
    pu_registers = alloc(16384); let data = alloc(256); let i = 0;
    while i < 256 { store8(data + i, i); i = i + 1; }
    if pe_uart_init(1, 1000000) != -22 || pe_uart_init(2, 9600) != -22 || pu_count { return 1; }
    if pe_uart_init(2, 1000000) || esp32_load32(0x3ff6e014) != 80 || esp32_load32(0x3ff6e020) != 0x0800001c { return 2; }
    if !(esp32_load32(0x3ff000c0) & (1 << 23)) || (esp32_load32(0x3ff000c4) & (1 << 23)) { return 3; }
    if esp32_load32(0x3ff44574) != (198 | 1024) || esp32_load32(0x3ff44448) != (16 | 128) { return 4; }
    if pe_uart_init(0, 115200) || esp32_load32(0x3ff40014) != (694 | (7 << 20)) { return 5; }
    let bus = 0; while bus <= 2 {
        let base = pe_uart_base(bus); let state = 0; while state < 16 {
            esp32_store32(base + 28, state << 8); if pe_uart_read(bus) != -1 || pu_reads || pu_mask { return 6; }
            esp32_store32(base + 28, state << 24); if pe_uart_idle(bus) != (state == 0) { return 7; }
            state = state + 1;
        }
        esp32_store32(base, 171); esp32_store32(base + 28, (15 << 8) | 1); pu_mask = 3;
        if pe_uart_read(bus) != 171 || pu_mask != 3 || pu_fault || pu_reads != 1 { return 8; } pu_reads = 0; pu_mask = 0;
        let count = 0; while count < 129 {
            esp32_store32(base + 28, count << 16); pu_writes = 0; let expected = 126 - count; if expected < 0 { expected = 0; }
            if pe_uart_write(bus, data, 256) != expected || pu_writes != expected { return 9; } count = count + 1;
        }
        let error = 4; while error <= 16 {
            esp32_store32(base + 4, error); if pe_uart_read(bus) != -5 || pu_mask { return 10; }
            if esp32_load32(base + 16) != 0x1ffff || esp32_load32(base + 32) & (3 << 17) { return 11; } error = error << 1;
        }
        bus = bus + 2;
    } return 0;
}
