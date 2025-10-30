#include "../../src/http.h"
#include "../../src/platform.h"
#include "bluetooth.h"

#include "../../src/motor_config.h"
#include "esp_app_desc.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mdns.h"
#include "nvs_flash.h"
#include "variant_config.h"
#include "wifi.h"

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

int storage_init(void) {
	esp_err_t ret = nvs_flash_init();
	if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
	    ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
		ESP_ERROR_CHECK(nvs_flash_erase());
		ret = nvs_flash_init();
	}
	return ret == ESP_OK ? 0 : -1;
}

const char *instance_name(void) { return PUPPY_INSTANCE_NAME; }

int wifi_init(void) {
	wifi_init_sta();
	return 0;
}

int mdns_service_init(void) {
	esp_err_t ret = mdns_init();
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to initialize mDNS: %s", esp_err_to_name(ret));
		return -1;
	}

	ret = mdns_hostname_set(PUPPY_HOSTNAME);
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to set hostname: %s", esp_err_to_name(ret));
		return -1;
	}

	ret = mdns_instance_name_set(PUPPY_INSTANCE_NAME);
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to set instance name: %s",
		         esp_err_to_name(ret));
		return -1;
	}

	ret = mdns_service_add(PUPPY_HOSTNAME, "_ws", "_tcp", 80, NULL, 0);
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to add service: %s", esp_err_to_name(ret));
		return -1;
	}

	char hostname_alias[32];
	snprintf(hostname_alias, sizeof(hostname_alias), "%s_1", PUPPY_HOSTNAME);
	mdns_hostname_set(hostname_alias);
	mdns_instance_name_set(PUPPY_INSTANCE_NAME);
	return 0;
}

void motor_init(void) { motor_system_init(); }

int bluetooth_start(void) { return bluetooth_app_start() == ESP_OK ? 0 : -1; }
