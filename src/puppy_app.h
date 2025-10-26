#ifndef PUPPY_APP_H
#define PUPPY_APP_H

#include <stdint.h>

typedef enum {
	PUPPY_APP_OK = 0,
	PUPPY_APP_ERR_STORAGE = -1,
	PUPPY_APP_ERR_WIFI = -2,
	PUPPY_APP_ERR_MDNS = -3,
	PUPPY_APP_ERR_BLUETOOTH = -4,
	PUPPY_APP_ERR_WEBSOCKET = -5,
} PuppyAppStatus;

// Main application entry point
// Uses HAL functions for platform-specific operations
PuppyAppStatus puppy_app_main(void);

#endif // PUPPY_APP_H
