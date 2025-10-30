#ifndef PUPPYBOT_MAIN_H
#define PUPPYBOT_MAIN_H

#include <stdint.h>

typedef enum {
	PUPPYBOT_OK = 0,
	PUPPYBOT_ERR_STORAGE = -1,
	PUPPYBOT_ERR_WIFI = -2,
	PUPPYBOT_ERR_MDNS = -3,
	PUPPYBOT_ERR_BLUETOOTH = -4,
	PUPPYBOT_ERR_WEBSOCKET = -5,
} PuppybotStatus;

// Main application entry point
// Uses platform APIs for platform-specific operations
PuppybotStatus puppybot_main(void);

#endif // PUPPYBOT_MAIN_H
