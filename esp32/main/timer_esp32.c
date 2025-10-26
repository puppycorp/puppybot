#include "../../src/timer.h"
#include "esp_log.h"
#include "esp_timer.h"

#define TAG "TIMER"

timer_t timer_create(void (*callback)(void *arg), void *arg, const char *name) {
	if (!callback) {
		return NULL;
	}

	esp_timer_handle_t timer = NULL;
	const esp_timer_create_args_t timer_args = {
	    .callback = callback,
	    .arg = arg,
	    .name = name,
	};

	esp_err_t ret = esp_timer_create(&timer_args, &timer);
	if (ret != ESP_OK) {
		ESP_LOGE(TAG, "Failed to create timer %s: %s",
		         name ? name : "(unnamed)", esp_err_to_name(ret));
		return NULL;
	}

	return (timer_t)timer;
}

int timer_start_once(timer_t timer, uint64_t timeout_us) {
	if (!timer) {
		return -1;
	}

	esp_err_t ret = esp_timer_start_once((esp_timer_handle_t)timer, timeout_us);
	return ret == ESP_OK ? 0 : -1;
}

int timer_stop(timer_t timer) {
	if (!timer) {
		return -1;
	}

	esp_err_t ret = esp_timer_stop((esp_timer_handle_t)timer);
	// ESP_ERR_INVALID_STATE means timer is not running, which is acceptable
	return (ret == ESP_OK || ret == ESP_ERR_INVALID_STATE) ? 0 : -1;
}

void timer_delete(timer_t timer) {
	if (timer) {
		esp_timer_delete((esp_timer_handle_t)timer);
	}
}
