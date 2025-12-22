#include "platform.h"
#include "bluetooth.h"
#include "http.h"
#include "nvs.h"

#include "esp_app_desc.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "variant_config.h"
#include "wifi.h"

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *PLATFORM_TAG = "PLATFORM";

#define BOT_ID_NAMESPACE "puppybot"
#define BOT_ID_KEY "bot_id"
#define CONFIG_BLOB_KEY "motor_config"

static char g_bot_id[PLATFORM_BOT_ID_MAX_LEN];
static bool g_bot_id_loaded = false;

static void load_stored_bot_id(void) {
	if (g_bot_id_loaded) {
		return;
	}
	g_bot_id_loaded = true;
	g_bot_id[0] = '\0';

	nvs_handle_t handle;
	esp_err_t err = nvs_open(BOT_ID_NAMESPACE, NVS_READWRITE, &handle);
	if (err != ESP_OK) {
		return;
	}

	size_t required = sizeof(g_bot_id);
	err = nvs_get_str(handle, BOT_ID_KEY, g_bot_id, &required);
	if (err != ESP_OK) {
		if (err != ESP_ERR_NVS_NOT_FOUND) {
			ESP_LOGW(PLATFORM_TAG, "Failed to read stored bot ID (%s)",
			         esp_err_to_name(err));
		}
		g_bot_id[0] = '\0';
	}

	nvs_close(handle);
}

#ifndef PUPPYBOT_BUILD_NAME
#define PUPPYBOT_BUILD_NAME "esp32"
#endif

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

const char *platform_get_bot_id(void) {
	load_stored_bot_id();
	if (g_bot_id[0]) {
		return g_bot_id;
	}
#if defined(DEVICE_ID)
	return DEVICE_ID;
#else
	return "1";
#endif
}

int platform_store_bot_id(const char *bot_id) {
	if (!bot_id || !bot_id[0]) {
		return -1;
	}
	size_t raw_len = strnlen(bot_id, PLATFORM_BOT_ID_MAX_LEN);
	if (raw_len == 0) {
		return -1;
	}
	if (raw_len >= PLATFORM_BOT_ID_MAX_LEN) {
		raw_len = PLATFORM_BOT_ID_MAX_LEN - 1;
	}
	char sanitized[PLATFORM_BOT_ID_MAX_LEN];
	memcpy(sanitized, bot_id, raw_len);
	sanitized[raw_len] = '\0';

	nvs_handle_t handle;
	esp_err_t err = nvs_open(BOT_ID_NAMESPACE, NVS_READWRITE, &handle);
	if (err != ESP_OK) {
		ESP_LOGE(PLATFORM_TAG, "Failed to open NVS for bot ID (%s)",
		         esp_err_to_name(err));
		return -1;
	}
	err = nvs_set_str(handle, BOT_ID_KEY, sanitized);
	if (err == ESP_OK) {
		err = nvs_commit(handle);
	}
	nvs_close(handle);
	if (err != ESP_OK) {
		ESP_LOGE(PLATFORM_TAG, "Failed to save bot ID (%s)",
		         esp_err_to_name(err));
		return -1;
	}
	strncpy(g_bot_id, sanitized, sizeof(g_bot_id));
	g_bot_id[sizeof(g_bot_id) - 1] = '\0';
	g_bot_id_loaded = true;
	return 0;
}

int platform_store_config_blob(const uint8_t *data, size_t len) {
	if (!data || len == 0) {
		return -1;
	}
	nvs_handle_t handle;
	esp_err_t err = nvs_open(BOT_ID_NAMESPACE, NVS_READWRITE, &handle);
	if (err != ESP_OK) {
		ESP_LOGE(PLATFORM_TAG, "Failed to open NVS for config (%s)",
		         esp_err_to_name(err));
		return -1;
	}
	err = nvs_set_blob(handle, CONFIG_BLOB_KEY, data, len);
	if (err == ESP_OK) {
		err = nvs_commit(handle);
	}
	nvs_close(handle);
	if (err != ESP_OK) {
		ESP_LOGE(PLATFORM_TAG, "Failed to save config blob (%s)",
		         esp_err_to_name(err));
		return -1;
	}
	return 0;
}

int platform_load_config_blob(uint8_t **out_data, size_t *out_len) {
	if (!out_data || !out_len) {
		return -1;
	}
	*out_data = NULL;
	*out_len = 0;
	nvs_handle_t handle;
	esp_err_t err = nvs_open(BOT_ID_NAMESPACE, NVS_READWRITE, &handle);
	if (err != ESP_OK) {
		ESP_LOGE(PLATFORM_TAG, "Failed to open NVS for config (%s)",
		         esp_err_to_name(err));
		return -1;
	}
	size_t required = 0;
	err = nvs_get_blob(handle, CONFIG_BLOB_KEY, NULL, &required);
	if (err == ESP_ERR_NVS_NOT_FOUND) {
		nvs_close(handle);
		return 1;
	}
	if (err != ESP_OK || required == 0) {
		nvs_close(handle);
		return -1;
	}
	uint8_t *buffer = (uint8_t *)malloc(required);
	if (!buffer) {
		nvs_close(handle);
		return -1;
	}
	err = nvs_get_blob(handle, CONFIG_BLOB_KEY, buffer, &required);
	nvs_close(handle);
	if (err != ESP_OK) {
		free(buffer);
		return -1;
	}
	*out_data = buffer;
	*out_len = required;
	return 0;
}

void platform_free_config_blob(uint8_t *data) {
	free(data);
}

const char *platform_get_server_uri(void) {
#if defined(SERVER_HOST)
	static char uri[256];
	const char *bot_id = platform_get_bot_id();
	if (!bot_id || bot_id[0] == '\0') {
		return NULL;
	}
	int needed = snprintf(uri, sizeof(uri),
	                      "ws://" SERVER_HOST "/api/bot/%s/ws", bot_id);
	if (needed < 0 || needed >= (int)sizeof(uri)) {
		ESP_LOGE(PLATFORM_TAG, "Server URI was truncated");
		return NULL;
	}
	return uri;
#else
	return NULL;
#endif
}

const char *instance_name(void) { return PUPPY_INSTANCE_NAME; }
