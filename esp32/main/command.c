#include "command.h"
#include "command_handler.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "motor.h"
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define TAG "COMMAND"
#define MSG_TO_SRV_PONG 0x01

// ESP-IDF specific timer operations
static CommandTimerHandle esp_timer_create_wrapper(void (*callback)(void *),
                                                   void *arg,
                                                   const char *name) {
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
	return (CommandTimerHandle)timer;
}

static int esp_timer_start_once_wrapper(CommandTimerHandle timer,
                                        uint64_t timeout_us) {
	if (!timer)
		return -1;
	esp_err_t ret = esp_timer_start_once((esp_timer_handle_t)timer, timeout_us);
	return ret == ESP_OK ? 0 : -1;
}

static int esp_timer_stop_wrapper(CommandTimerHandle timer) {
	if (!timer)
		return -1;
	esp_err_t ret = esp_timer_stop((esp_timer_handle_t)timer);
	// ESP_ERR_INVALID_STATE means timer is not running, which is acceptable
	return (ret == ESP_OK || ret == ESP_ERR_INVALID_STATE) ? 0 : -1;
}

// ESP-IDF specific logging operations
static void esp_log_vwrapper(esp_log_level_t level, const char *tag,
                             const char *format, va_list args) {
	char stack_buffer[128];
	char *buffer = stack_buffer;
	size_t buffer_size = sizeof(stack_buffer);

	va_list args_copy;
	va_copy(args_copy, args);
	int needed = vsnprintf(stack_buffer, buffer_size, format, args_copy);
	va_end(args_copy);

	if (needed < 0) {
		return;
	}

	if (needed >= (int)buffer_size) {
		buffer_size = (size_t)needed + 1;
		buffer = (char *)malloc(buffer_size);
		if (buffer) {
			va_list args_full;
			va_copy(args_full, args);
			vsnprintf(buffer, buffer_size, format, args_full);
			va_end(args_full);
		} else {
			buffer = stack_buffer;
			if (sizeof(stack_buffer) >= 4) {
				stack_buffer[sizeof(stack_buffer) - 4] = '.';
				stack_buffer[sizeof(stack_buffer) - 3] = '.';
				stack_buffer[sizeof(stack_buffer) - 2] = '.';
			}
			stack_buffer[sizeof(stack_buffer) - 1] = '\0';
		}
	}

	switch (level) {
	case ESP_LOG_ERROR:
		ESP_LOGE(tag, "%s", buffer);
		break;
	case ESP_LOG_WARN:
		ESP_LOGW(tag, "%s", buffer);
		break;
	case ESP_LOG_DEBUG:
		ESP_LOGD(tag, "%s", buffer);
		break;
	case ESP_LOG_VERBOSE:
		ESP_LOGV(tag, "%s", buffer);
		break;
	default:
		ESP_LOGI(tag, "%s", buffer);
		break;
	}

	if (buffer != stack_buffer) {
		free(buffer);
	}
}

static void esp_log_warning_wrapper(const char *tag, const char *format, ...) {
	va_list args;
	va_start(args, format);
	esp_log_vwrapper(ESP_LOG_WARN, tag, format, args);
	va_end(args);
}

static void esp_log_error_wrapper(const char *tag, const char *format, ...) {
	va_list args;
	va_start(args, format);
	esp_log_vwrapper(ESP_LOG_ERROR, tag, format, args);
	va_end(args);
}

static void esp_log_info_wrapper(const char *tag, const char *format, ...) {
	va_list args;
	va_start(args, format);
	esp_log_vwrapper(ESP_LOG_INFO, tag, format, args);
	va_end(args);
}

// ESP-IDF specific servo operations
static void esp_servo_set_angle_wrapper(uint8_t servo_id, uint32_t angle) {
	servo_set_angle(servo_id, angle);
}

static uint32_t esp_servo_count_wrapper(void) { return motor_servo_count(); }

static uint32_t esp_servo_boot_angle_wrapper(uint8_t servo_id) {
	return motor_servo_boot_angle(servo_id);
}

// ESP-IDF specific websocket operations
static int esp_websocket_send_pong_wrapper(void *client) {
	if (!client)
		return -1;
	esp_websocket_client_handle_t ws_client =
	    (esp_websocket_client_handle_t)client;
	char buff[] = {1, 0, MSG_TO_SRV_PONG};
	int ret = esp_websocket_client_send_bin(ws_client, buff, sizeof(buff),
	                                        portMAX_DELAY);
	return ret >= 0 ? 0 : -1;
}

// Command operations structure
static const CommandOps esp_command_ops = {
    .timer_create = esp_timer_create_wrapper,
    .timer_start_once = esp_timer_start_once_wrapper,
    .timer_stop = esp_timer_stop_wrapper,
    .log_info = esp_log_info_wrapper,
    .log_warning = esp_log_warning_wrapper,
    .log_error = esp_log_error_wrapper,
    .servo_set_angle = esp_servo_set_angle_wrapper,
    .servo_count = esp_servo_count_wrapper,
    .servo_boot_angle = esp_servo_boot_angle_wrapper,
    .websocket_send_pong = esp_websocket_send_pong_wrapper,
};

void init_command_handler() { command_handler_init(&esp_command_ops); }

void handle_command(CommandPacket *cmd, esp_websocket_client_handle_t client) {
	if (!cmd)
		return;
	if (cmd->cmd_type == CMD_APPLY_CONFIG) {
		if (!cmd->cmd.apply_config.data || cmd->cmd.apply_config.length == 0) {
			ESP_LOGW(TAG, "Received empty PBCL config payload");
			return;
		}
		int rc = motor_apply_pbcl_blob(cmd->cmd.apply_config.data,
		                               cmd->cmd.apply_config.length);
		if (rc != 0) {
			ESP_LOGE(TAG, "motor_apply_pbcl_blob failed (%d)", rc);
		} else {
			ESP_LOGI(TAG, "Motor configuration applied (%u bytes)",
			         (unsigned)cmd->cmd.apply_config.length);
			command_handler_reload_motor_config();
		}
		return;
	}
	command_handler_handle(cmd, (void *)client);
}
