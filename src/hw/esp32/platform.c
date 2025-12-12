#include "platform.h"
#include "bluetooth.h"
#include "http.h"

#include "esp_app_desc.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "variant_config.h"
#include "wifi.h"

int storage_init(void);
int wifi_init(void);
int mdns_service_init(void);
void motor_init(void);

PuppybotStatus platform_init(void) {
	if (storage_init() != 0) {
		return PUPPYBOT_ERR_STORAGE;
	}
	if (wifi_init() != 0) {
		return PUPPYBOT_ERR_WIFI;
	}
	if (mdns_service_init() != 0) {
		return PUPPYBOT_ERR_MDNS;
	}
	motor_init();
	return PUPPYBOT_OK;
}

uint32_t platform_get_time_ms(void) {
	return (uint32_t)(esp_timer_get_time() / 1000);
}

const char *platform_get_firmware_version(void) {
	const esp_app_desc_t *app_desc = esp_app_get_description();
	return app_desc ? app_desc->version : "unknown";
}

const char *platform_get_server_uri(void) {
#if defined(SERVER_HOST) && defined(DEVICE_ID)
	return "ws://" SERVER_HOST "/api/bot/" DEVICE_ID "/ws";
#elif defined(SERVER_HOST)
	return "ws://" SERVER_HOST "/api/bot/1/ws";
#else
	return NULL;
#endif
}

const char *instance_name(void) { return PUPPY_INSTANCE_NAME; }
