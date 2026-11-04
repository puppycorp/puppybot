// Original ESP32 only. Single PRO CPU; APP CPU stays held in reset.
// ROM entry points pinned to ESP-IDF v5.5.1 esp32.rom.ld, cache.h.
// Link --target esp32-radio-elf with scripts/esp32-link --xip.
fn esp_xip_enable() {
    let ps=esp32_irq_save();
    esp32_call32(0x40009ab8,0,0,0,0,0,0,0,0);
    esp32_call32(0x40009a14,0,0,0,0,0,0,0,0);
    // Reset stale ROM/download-mode translations before installing mappings.
    // Cache_Read_Init alone leaves them intact on physical ESP32 silicon.
    esp32_call32(0x400095a4,0,0,0,0,0,0,0,0);
    // ROM boot loads RAM via SPI1; initialize SPI0 for cache reads as well.
    let pins=esp32_call32(0x40008658,0,0,0,0,0,0,0,0);
    esp32_call32(0x40062a6c,pins,0,0,0,0,0,0,0);
    let result=0;let count=esp32_external("_flex_irom_pages");
    if count {result=esp32_call32(0x400095e0,0,0,0x400d0000,esp32_external("_flex_irom_flash"),64,count,0,0);}
    count=esp32_external("_flex_drom_pages");
    if !result && count {result=esp32_call32(0x400095e0,0,0,0x3f400000,esp32_external("_flex_drom_flash"),64,count,0,0);}
    // 0x400d0000 uses IBUS0 (IRAM0), not the register's IROM0 bus.
    // See ESP-IDF v5.5.1 cache_ll_l1_get_bus/cache_ll_l1_enable_bus.
    esp32_store32(0x3ff00044,esp32_load32(0x3ff00044)&~17);
    esp32_call32(0x40009a84,0,0,0,0,0,0,0,0);
    esp32_irq_restore(ps);return result;
}
