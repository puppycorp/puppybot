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
	PuppybotStatus init_status = platform_init();
	if (init_status != PUPPYBOT_OK) {
		return init_status;
	}

	// Log boot message
	const char *instance = instance_name();
	log_info(TAG, "Booting %s", instance);

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
