#include "command.h"
#include "command_handler.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "motor.h"
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>

#define TAG "COMMAND"
#define MSG_TO_SRV_PONG 0x01

// ESP-IDF specific timer operations
static CommandTimerHandle esp_timer_create_wrapper(void (*callback)(void *),
                                                    void *arg, const char *name) {
	esp_timer_handle_t timer = NULL;
	const esp_timer_create_args_t timer_args = {
	    .callback = callback,
	    .arg = arg,
	    .name = name,
	};
	esp_err_t ret = esp_timer_create(&timer_args, &timer);
	if (ret != ESP_OK) {
		ESP_LOGE(TAG, "Failed to create timer %s: %s", name ? name : "(unnamed)",
		         esp_err_to_name(ret));
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
static void esp_log_info_wrapper(const char *tag, const char *format, ...) {
	va_list args;
	va_start(args, format);
	esp_log_write(ESP_LOG_INFO, tag, LOG_FORMAT(I, format), esp_log_timestamp(),
	              tag, args);
	va_end(args);
}

static void esp_log_warning_wrapper(const char *tag, const char *format, ...) {
	va_list args;
	va_start(args, format);
	esp_log_write(ESP_LOG_WARN, tag, LOG_FORMAT(W, format), esp_log_timestamp(),
	              tag, args);
	va_end(args);
}

static void esp_log_error_wrapper(const char *tag, const char *format, ...) {
	va_list args;
	va_start(args, format);
	esp_log_write(ESP_LOG_ERROR, tag, LOG_FORMAT(E, format),
	              esp_log_timestamp(), tag, args);
	va_end(args);
}

// ESP-IDF specific motor control operations
static void esp_motor_a_forward_wrapper(uint8_t speed) { motorA_forward(speed); }

static void esp_motor_a_backward_wrapper(uint8_t speed) {
	motorA_backward(speed);
}

static void esp_motor_a_stop_wrapper(void) { motorA_stop(); }

static void esp_motor_b_forward_wrapper(uint8_t speed) { motorB_forward(speed); }

static void esp_motor_b_backward_wrapper(uint8_t speed) {
	motorB_backward(speed);
}

static void esp_motor_b_stop_wrapper(void) { motorB_stop(); }

// ESP-IDF specific servo operations
static void esp_servo_set_angle_wrapper(uint8_t servo_id, uint32_t angle) {
	servo_set_angle(servo_id, angle);
}

static uint32_t esp_servo_count_wrapper(void) { return PUPPY_SERVO_COUNT; }

static uint32_t esp_servo_boot_angle_wrapper(uint8_t servo_id) {
	return puppy_servo_boot_angle(servo_id);
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
    .motor_a_forward = esp_motor_a_forward_wrapper,
    .motor_a_backward = esp_motor_a_backward_wrapper,
    .motor_a_stop = esp_motor_a_stop_wrapper,
    .motor_b_forward = esp_motor_b_forward_wrapper,
    .motor_b_backward = esp_motor_b_backward_wrapper,
    .motor_b_stop = esp_motor_b_stop_wrapper,
    .servo_set_angle = esp_servo_set_angle_wrapper,
    .servo_count = esp_servo_count_wrapper,
    .servo_boot_angle = esp_servo_boot_angle_wrapper,
    .websocket_send_pong = esp_websocket_send_pong_wrapper,
};

void init_command_handler() { command_handler_init(&esp_command_ops); }

void handle_command(CommandPacket *cmd, esp_websocket_client_handle_t client) {
	command_handler_handle(cmd, (void *)client);
}
