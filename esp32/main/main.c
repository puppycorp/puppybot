#include "../../src/main.h"
#include "esp_log.h"

void app_main(void) {
	PuppybotStatus status = puppybot_main();
	if (status != PUPPYBOT_OK) {
		ESP_LOGE("MAIN", "puppybot_main failed (%d)", (int)status);
	}
}
