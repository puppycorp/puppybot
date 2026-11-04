/* No external libraries. The Flexscript linker resolves the four XIP symbols.
 * Classic ESP32 ROM calls in vendor/esp32-xip.flex use pinned absolute addresses.
 */
PROVIDE(puppybot_firmware_version = 1);
