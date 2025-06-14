#include "bluetooth.h"
#include "esp_err.h"
#include "motor.h"
#include "nvs_flash.h"
#include "wifi.h"
#include "ws.h"
#include <stdio.h>

void app_main(void) {
	esp_err_t ret = nvs_flash_init();
	if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
	    ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
		ESP_ERROR_CHECK(nvs_flash_erase());
		ret = nvs_flash_init();
	}
	ESP_ERROR_CHECK(ret);

	wifi_init_sta();

	motor_gpio_init();
	motor_pwm_init();
	servo_set_angle(95); // center wheels

	vTaskDelay(pdMS_TO_TICKS(5000));

	websocket_app_start();
}
