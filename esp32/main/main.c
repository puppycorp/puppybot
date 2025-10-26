#include "esp_log.h"
#include "puppy_app.h"

void app_main(void) {
	PuppyAppStatus status = puppy_app_main();
	if (status != PUPPY_APP_OK) {
		ESP_LOGE("MAIN", "puppy_app_main failed (%d)", (int)status);
	}
}
