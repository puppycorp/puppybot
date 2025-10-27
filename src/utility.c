#include "utility.h"

#ifdef ESP_PLATFORM
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#else
#include <sys/time.h>
#include <unistd.h>
#endif

uint32_t now_ms(void) {
#ifdef ESP_PLATFORM
	return (uint32_t)(esp_timer_get_time() / 1000);
#else
	struct timeval tv;
	gettimeofday(&tv, NULL);
	uint64_t ms = (uint64_t)tv.tv_sec * 1000ULL + tv.tv_usec / 1000ULL;
	return (uint32_t)ms;
#endif
}

void delay_ms(uint32_t ms) {
#ifdef ESP_PLATFORM
	vTaskDelay(pdMS_TO_TICKS(ms));
#else
	usleep(ms * 1000);
#endif
}
