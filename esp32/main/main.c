#include "bluetooth.h"
#include "esp_err.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mdns.h"
#include "motor.h"
#include "nvs_flash.h"
#include "puppy_app.h"
#include "variant_config.h"
#include "wifi.h"
#include "ws.h"
#include <stdint.h>
#include <stdio.h>

static int esp_storage_init(void) {
	esp_err_t ret = nvs_flash_init();
	if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
	    ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
		ESP_ERROR_CHECK(nvs_flash_erase());
		ret = nvs_flash_init();
	}
	return ret == ESP_OK ? 0 : -1;
}

static const char *esp_instance_name(void) { return PUPPY_INSTANCE_NAME; }

static void esp_log_boot(const char *instance_name) {
	ESP_LOGI("MAIN", "Booting %s firmware variant", instance_name);
}

static int esp_wifi_init(void) {
	wifi_init_sta();
	return 0;
}

static int esp_mdns_init(void) {
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

static void esp_motor_gpio_init(void) { motor_gpio_init(); }

static void esp_motor_pwm_init(void) { motor_pwm_init(); }

static uint32_t esp_servo_count(void) { return SERVO_COUNT; }

static uint32_t esp_servo_boot_angle(uint32_t servo) {
	return puppy_servo_boot_angle((uint8_t)servo);
}

static void esp_servo_set_angle(uint32_t servo, uint32_t angle) {
	servo_set_angle((uint8_t)servo, angle);
}

static void esp_delay_ms(uint32_t ms) { vTaskDelay(pdMS_TO_TICKS(ms)); }

static void esp_command_handler_init(void) { init_command_handler(); }

static int esp_bluetooth_start(void) {
	return bluetooth_app_start() == ESP_OK ? 0 : -1;
}

static int esp_websocket_start(void) {
	websocket_app_start();
	return 0;
}

void app_main(void) {
	PuppyHardwareOps ops = {
	    .storage_init = esp_storage_init,
	    .instance_name = esp_instance_name,
	    .log_boot = esp_log_boot,
	    .wifi_init = esp_wifi_init,
	    .mdns_init = esp_mdns_init,
	    .motor_gpio_init = esp_motor_gpio_init,
	    .motor_pwm_init = esp_motor_pwm_init,
	    .servo_count = esp_servo_count,
	    .servo_boot_angle = esp_servo_boot_angle,
	    .servo_set_angle = esp_servo_set_angle,
	    .delay_ms = esp_delay_ms,
	    .command_handler_init = esp_command_handler_init,
	    .bluetooth_start = esp_bluetooth_start,
	    .websocket_start = esp_websocket_start,
	};

	PuppyAppStatus status = puppy_app_main(&ops);
	if (status != PUPPY_APP_OK) {
		ESP_LOGE("MAIN", "puppy_app_main failed (%d)", (int)status);
	}
}
