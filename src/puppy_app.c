#include "puppy_app.h"

#include <stddef.h>

#define PUPPY_APP_BOOT_DELAY_MS 5000U

static PuppyAppStatus call_optional_int(int (*fn)(void),
                                        PuppyAppStatus error_code) {
	if (!fn) {
		return PUPPY_APP_OK;
	}
	int rc = fn();
	return rc == 0 ? PUPPY_APP_OK : error_code;
}

PuppyAppStatus puppy_app_main(const PuppyHardwareOps *ops) {
	if (!ops) {
		return PUPPY_APP_ERR_INVALID_ARGUMENT;
	}

	PuppyAppStatus status =
	    call_optional_int(ops->storage_init, PUPPY_APP_ERR_STORAGE);
	if (status != PUPPY_APP_OK) {
		return status;
	}

	const char *instance = ops->instance_name ? ops->instance_name() : "Puppy";
	if (ops->log_boot) {
		ops->log_boot(instance);
	}

	status = call_optional_int(ops->wifi_init, PUPPY_APP_ERR_WIFI);
	if (status != PUPPY_APP_OK) {
		return status;
	}

	status = call_optional_int(ops->mdns_init, PUPPY_APP_ERR_MDNS);
	if (status != PUPPY_APP_OK) {
		return status;
	}

	if (ops->motor_gpio_init) {
		ops->motor_gpio_init();
	}
	if (ops->motor_pwm_init) {
		ops->motor_pwm_init();
	}

	uint32_t servo_count = ops->servo_count ? ops->servo_count() : 0;
	for (uint32_t servo = 0; servo < servo_count; ++servo) {
		if (!ops->servo_set_angle) {
			break;
		}
		uint32_t angle =
		    ops->servo_boot_angle ? ops->servo_boot_angle(servo) : 90U;
		ops->servo_set_angle(servo, angle);
	}

	if (ops->delay_ms) {
		ops->delay_ms(PUPPY_APP_BOOT_DELAY_MS);
	}

	if (ops->command_handler_init) {
		ops->command_handler_init();
	}

	status = call_optional_int(ops->bluetooth_start, PUPPY_APP_ERR_BLUETOOTH);
	if (status != PUPPY_APP_OK) {
		return status;
	}

	status = call_optional_int(ops->websocket_start, PUPPY_APP_ERR_WEBSOCKET);
	if (status != PUPPY_APP_OK) {
		return status;
	}

	return PUPPY_APP_OK;
}
