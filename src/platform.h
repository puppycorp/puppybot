#include <stdint.h>

// Platform initialization and utilities

// Initialize platform storage (NVS, filesystem, etc.)
// Returns 0 on success, non-zero on error
int storage_init(void);

// Get device instance name
const char *instance_name(void);

// Initialize WiFi
// Returns 0 on success, non-zero on error
int wifi_init(void);

// Initialize mDNS service discovery
// Returns 0 on success, non-zero on error
int mdns_service_init(void);

// Initialize motor system
void motor_init(void);

// Start Bluetooth service
// Returns 0 on success, non-zero on error
int bluetooth_start(void);

// Start WebSocket service
// Returns 0 on success, non-zero on error
int websocket_start(void);
