#include "main.h"
#include "command_handler.h"
#include "http.h"
#include "log.h"
#include "motor_slots.h"
#include "platform.h"
#include "utility.h"

#define PUPPYBOT_BOOT_DELAY_MS 5000U
#define HEARTBEAT_INTERVAL_MS 30000
#define TAG "PUPPYBOT"

PuppybotStatus puppybot_main(void) {
	// Initialize storage
	if (storage_init() != 0) {
		return PUPPYBOT_ERR_STORAGE;
	}

	// Log boot message
	const char *instance = instance_name();
	log_info(TAG, "Booting %s", instance);

	// Initialize WiFi
	if (wifi_init() != 0) {
		return PUPPYBOT_ERR_WIFI;
	}

	// Initialize mDNS
	if (mdns_service_init() != 0) {
		return PUPPYBOT_ERR_MDNS;
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
	delay_ms(PUPPYBOT_BOOT_DELAY_MS);

	// Initialize command handler
	command_handler_init();

	// Start Bluetooth
	if (bluetooth_start() != 0) {
		return PUPPYBOT_ERR_BLUETOOTH;
	}

	// Start HTTP server and WebSocket client
	http_server_start();
	const char *server_uri = platform_get_server_uri();
	http_client_start(server_uri, HEARTBEAT_INTERVAL_MS);

	return PUPPYBOT_OK;
}
