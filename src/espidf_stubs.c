#include "espidf_stubs.h"

#ifndef ESP_PLATFORM

#include <string.h>

gpio_config_call_t gpio_config_last_call = {0};
ledc_timer_config_call_t ledc_timer_config_last_call = {0};
ledc_channel_config_call_t ledc_channel_config_last_call = {0};
ledc_set_duty_call_t ledc_set_duty_last_call = {0};
ledc_update_duty_call_t ledc_update_duty_last_call = {0};
gpio_set_level_call_t gpio_set_level_last_call = {0};

void espidf_stubs_reset(void) {
	memset(&gpio_config_last_call, 0, sizeof(gpio_config_last_call));
	memset(&ledc_timer_config_last_call, 0,
	       sizeof(ledc_timer_config_last_call));
	memset(&ledc_channel_config_last_call, 0,
	       sizeof(ledc_channel_config_last_call));
	memset(&ledc_set_duty_last_call, 0, sizeof(ledc_set_duty_last_call));
	memset(&ledc_update_duty_last_call, 0, sizeof(ledc_update_duty_last_call));
	memset(&gpio_set_level_last_call, 0, sizeof(gpio_set_level_last_call));
}

esp_err_t gpio_config(const gpio_config_t *config) {
	gpio_config_last_call.called = true;
	gpio_config_last_call.call_count++;
	if (config) {
		gpio_config_last_call.config = *config;
	}
	return ESP_OK;
}

esp_err_t ledc_timer_config(const ledc_timer_config_t *config) {
	ledc_timer_config_last_call.called = true;
	ledc_timer_config_last_call.call_count++;
	if (config) {
		ledc_timer_config_last_call.config = *config;
	}
	return ESP_OK;
}

esp_err_t ledc_channel_config(const ledc_channel_config_t *config) {
	ledc_channel_config_last_call.called = true;
	ledc_channel_config_last_call.call_count++;
	if (config) {
		ledc_channel_config_last_call.config = *config;
	}
	return ESP_OK;
}

esp_err_t ledc_set_duty(ledc_mode_t speed_mode, ledc_channel_t channel,
                        uint32_t duty) {
	ledc_set_duty_last_call.called = true;
	ledc_set_duty_last_call.call_count++;
	ledc_set_duty_last_call.mode = speed_mode;
	ledc_set_duty_last_call.channel = channel;
	ledc_set_duty_last_call.duty = duty;
	return ESP_OK;
}

esp_err_t ledc_update_duty(ledc_mode_t speed_mode, ledc_channel_t channel) {
	ledc_update_duty_last_call.called = true;
	ledc_update_duty_last_call.call_count++;
	ledc_update_duty_last_call.mode = speed_mode;
	ledc_update_duty_last_call.channel = channel;
	return ESP_OK;
}

esp_err_t gpio_set_level(gpio_num_t gpio, int level) {
	gpio_set_level_last_call.called = true;
	gpio_set_level_last_call.call_count++;
	gpio_set_level_last_call.gpio = gpio;
	gpio_set_level_last_call.level = level;
	return ESP_OK;
}

#endif // ESP_PLATFORM
