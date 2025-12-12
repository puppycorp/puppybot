#include "main.h"

#include <stdint.h>

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

// Platform-specific services (storage/WiFi/mDNS/motor) are initialized
// internally by platform_init().

// Start Bluetooth service after app subsystems are ready.
// Returns 0 on success, non-zero on error.
int bluetooth_start(void);
