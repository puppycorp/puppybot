#include "main.h"

#include <stddef.h>
#include <stdint.h>

#define PLATFORM_BOT_ID_MAX_LEN 64

// Platform initialization and utilities

// Get current time in milliseconds
// Returns monotonic time suitable for timing/intervals
uint32_t platform_get_time_ms(void);

// Get firmware version string
// Returns firmware version (e.g., "1.0.0") or "unknown"
const char *platform_get_firmware_version(void);

// Get WebSocket server URI for connecting to backend
// Returns URI string (e.g., "ws://server/api/bot/123/ws") or NULL if not
// configured
const char *platform_get_server_uri(void);

// Initialize platform-specific subsystems required for boot.
// Returns a PuppybotStatus error code.
PuppybotStatus platform_init(void);

// Get device instance name
const char *instance_name(void);

// Read/write the runtime bot identifier that the server assigned
const char *platform_get_bot_id(void);
int platform_store_bot_id(const char *bot_id);

// Persist/retrieve the latest motor config blob (PBCL) for this device.
// Returns 0 on success, 1 if not found, negative on error.
int platform_store_config_blob(const uint8_t *data, size_t len);
int platform_load_config_blob(uint8_t **out_data, size_t *out_len);
void platform_free_config_blob(uint8_t *data);

// Platform-specific services (storage/WiFi/mDNS/motor) are initialized
// internally by platform_init().

// Start Bluetooth service after app subsystems are ready.
// Returns 0 on success, non-zero on error.
int bluetooth_start(void);
