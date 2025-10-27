#include "puppy_app.h"
#include "command_handler.h"
#include "log.h"
#include "motor_slots.h"
#include "platform.h"
#include "utility.h"

#define PUPPY_APP_BOOT_DELAY_MS 5000U
#define TAG "PUPPY_APP"

PuppyAppStatus puppy_app_main(void) {
	// Initialize storage
	if (storage_init() != 0) {
		return PUPPY_APP_ERR_STORAGE;
	}

	// Log boot message
	const char *instance = instance_name();
	log_info(TAG, "Booting %s", instance);

	// Initialize WiFi
	if (wifi_init() != 0) {
		return PUPPY_APP_ERR_WIFI;
	}

	// Initialize mDNS
	if (mdns_service_init() != 0) {
		return PUPPY_APP_ERR_MDNS;
	}

	// Initialize motor system
	motor_init();

	// Set servos to boot angles
	int servo_count = motor_slots_servo_count();
	for (int servo = 0; servo < servo_count; ++servo) {
		float boot_angle = motor_slots_servo_boot_angle(servo);
		if (boot_angle < 0.0f)
			boot_angle = 90.0f;
		// This will be handled by the motor system through motor_slots
		// No direct HAL call needed since servo angles are managed by
		// motor_runtime
	}

	// Boot delay
	delay_ms(PUPPY_APP_BOOT_DELAY_MS);

	// Initialize command handler
	command_handler_init();

	// Start Bluetooth
	if (bluetooth_start() != 0) {
		return PUPPY_APP_ERR_BLUETOOTH;
	}

	// Start WebSocket
	if (websocket_start() != 0) {
		return PUPPY_APP_ERR_WEBSOCKET;
	}

	return PUPPY_APP_OK;
}
