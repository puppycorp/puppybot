#ifndef PUPPY_APP_H
#define PUPPY_APP_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
	PUPPY_APP_OK = 0,
	PUPPY_APP_ERR_INVALID_ARGUMENT = -1,
	PUPPY_APP_ERR_STORAGE = -2,
	PUPPY_APP_ERR_WIFI = -3,
	PUPPY_APP_ERR_MDNS = -4,
	PUPPY_APP_ERR_BLUETOOTH = -5,
	PUPPY_APP_ERR_WEBSOCKET = -6,
} PuppyAppStatus;

typedef struct PuppyHardwareOps {
	int (*storage_init)(void);
	const char *(*instance_name)(void);
	void (*log_boot)(const char *instance_name);
	int (*wifi_init)(void);
	int (*mdns_init)(void);
	void (*motor_gpio_init)(void);
	void (*motor_pwm_init)(void);
	uint32_t (*servo_count)(void);
	uint32_t (*servo_boot_angle)(uint32_t servo_id);
	void (*servo_set_angle)(uint32_t servo_id, uint32_t angle);
	void (*delay_ms)(uint32_t ms);
	void (*command_handler_init)(void);
	int (*bluetooth_start)(void);
	int (*websocket_start)(void);
} PuppyHardwareOps;

PuppyAppStatus puppy_app_main(const PuppyHardwareOps *ops);

#ifdef __cplusplus
}
#endif

#endif // PUPPY_APP_H
