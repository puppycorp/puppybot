#include "esp_log.h"
#include "log.h"
#include <stdarg.h>
#include <stdio.h>

#define LOG_BUFFER_SIZE 256

void log_info(const char *tag, const char *format, ...) {
	char buffer[LOG_BUFFER_SIZE];
	va_list args;
	va_start(args, format);
	vsnprintf(buffer, sizeof(buffer), format, args);
	va_end(args);
	ESP_LOGI(tag, "%s", buffer);
}

void log_warn(const char *tag, const char *format, ...) {
	char buffer[LOG_BUFFER_SIZE];
	va_list args;
	va_start(args, format);
	vsnprintf(buffer, sizeof(buffer), format, args);
	va_end(args);
	ESP_LOGW(tag, "%s", buffer);
}

void log_error(const char *tag, const char *format, ...) {
	char buffer[LOG_BUFFER_SIZE];
	va_list args;
	va_start(args, format);
	vsnprintf(buffer, sizeof(buffer), format, args);
	va_end(args);
	ESP_LOGE(tag, "%s", buffer);
}
