#include "bluetooth.h"
#include "esp_err.h"
#include "nvs_flash.h"
#include "wifi.h"
#include "mdns.h"
#include "ws.h"
#include "motor.h"
#include <stdio.h>

void my_mdns_init(void) {
	esp_err_t ret = mdns_init();
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to initialize mDNS: %s", esp_err_to_name(ret));
		return;
	}

	// Set the hostname and instance name:
	ret = mdns_hostname_set("puppybot");
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to set hostname: %s", esp_err_to_name(ret));
		return;
	}

	ret = mdns_instance_name_set("PuppyBot");
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to set instance name: %s", esp_err_to_name(ret));
		return;
	}

	// Add a service:
	ret = mdns_service_add("puppybot", "_ws", "_tcp", 80, NULL, 0);
	ESP_ERROR_CHECK(ret);
    mdns_hostname_set("puppybot_1");        // A/AAAA
    mdns_instance_name_set("PuppyBot");

    // Advertise the WebSocket service:
    mdns_service_add("ws", "_ws", "_tcp", 80, NULL, 0);    // PTR + SRV

    // Optional TXT key=value metadata
    mdns_service_txt_item_set("_ws", "_tcp", "fw",  "1.3.2");
    mdns_service_txt_item_set("_ws", "_tcp", "role","gateway");
}

void app_main(void) {
	esp_err_t ret = nvs_flash_init();
	if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
	    ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
		ESP_ERROR_CHECK(nvs_flash_erase());
		ret = nvs_flash_init();
	}
	ESP_ERROR_CHECK(ret);

	wifi_init_sta();
	//my_mdns_init();

	motor_gpio_init();
	motor_pwm_init();
	servo_set_angle(88); // center wheels

	vTaskDelay(pdMS_TO_TICKS(5000));

	init_command_handler();
	websocket_app_start();
}
