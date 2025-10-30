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

// Initialize platform storage (NVS, filesystem, etc.)
// Returns 0 on success, non-zero on error
int storage_init(void);

// Get device instance name
const char *instance_name(void);

// Initialize WiFi
// Returns 0 on success, non-zero on error
int wifi_init(void);

// Platform timer support -----------------------------------------------------

typedef void *platform_timer_handle_t;

platform_timer_handle_t platform_timer_create(void (*callback)(void *arg),
                                              void *arg, uint32_t interval_ms);
int platform_timer_start(platform_timer_handle_t timer);
int platform_timer_stop(platform_timer_handle_t timer);
void platform_timer_delete(platform_timer_handle_t timer);
void platform_delay_ms(uint32_t ms);

// Initialize mDNS service discovery
// Returns 0 on success, non-zero on error
int mdns_service_init(void);

// Initialize motor system
void motor_init(void);

// Start Bluetooth service
// Returns 0 on success, non-zero on error
int bluetooth_start(void);
