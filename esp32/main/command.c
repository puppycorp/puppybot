#include "command.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "motor.h"
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#define TAG "COMMAND"

esp_timer_handle_t safety_timer;
typedef struct {
	esp_timer_handle_t timer;
	uint16_t restore_angle;
	bool active;
} servo_timeout_state_t;

static servo_timeout_state_t servo_timeouts[PUPPY_SERVO_COUNT];
static uint16_t servo_current_angle[PUPPY_SERVO_COUNT];

static void servo_timeout_callback(void *arg) {
	uint32_t servo_id = (uint32_t)(uintptr_t)arg;
	if (servo_id >= PUPPY_SERVO_COUNT) {
		return;
	}
	servo_timeout_state_t *state = &servo_timeouts[servo_id];
	ESP_LOGI(TAG, "Servo %lu timeout -> restoring to %d", (unsigned long)servo_id,
	         state->restore_angle);
	servo_set_angle((uint8_t)servo_id, state->restore_angle);
	servo_current_angle[servo_id] = state->restore_angle;
	state->active = false;
}

static void cancel_servo_timeout(uint8_t servo_id) {
	if (servo_id >= PUPPY_SERVO_COUNT) {
		return;
	}
	servo_timeout_state_t *state = &servo_timeouts[servo_id];
	if (state->timer == NULL) {
		return;
	}
	esp_err_t stop_result = esp_timer_stop(state->timer);
	if (stop_result != ESP_OK && stop_result != ESP_ERR_INVALID_STATE) {
		ESP_LOGW(TAG, "Failed to stop servo timeout %u: %s", servo_id,
		         esp_err_to_name(stop_result));
	}
	state->active = false;
}

void safety_timer_callback(void *arg) {
	ESP_LOGW(TAG, "Safety timeout: stopping all motors");
	motorA_stop();
	motorB_stop();
}

static uint8_t speed_to_duty(int speed) {
	int magnitude = abs(speed);
	if (magnitude > 127) {
		magnitude = 127;
	}

	// Map 0..127 -> 0..255 for LEDC 8-bit duty cycle
	return (uint8_t)((magnitude * 255) / 127);
}

void handle_command(CommandPacket *cmd, esp_websocket_client_handle_t client) {
	switch (cmd->cmd_type) {
	case CMD_PING:
		ESP_LOGI(TAG, "Ping command received");
		if (client) {
			char buff[] = {1, 0, MSG_TO_SRV_PONG};
			esp_websocket_client_send_bin(client, buff, sizeof(buff),
			                              portMAX_DELAY);
		}
		break;
	case CMD_DRIVE_MOTOR:
		ESP_LOGI(TAG, "drive motor %d with speed %d",
		         cmd->cmd.drive_motor.motor_id, cmd->cmd.drive_motor.speed);
		// Reset the safety timer
		if (safety_timer) {
			esp_timer_stop(safety_timer);
			esp_timer_start_once(safety_timer, 1000000); // 1 second timeout
		}
		if (cmd->cmd.drive_motor.motor_type == SERVO_MOTOR) {
			uint8_t servo_id = (uint8_t)cmd->cmd.drive_motor.motor_id;
			if (servo_id >= PUPPY_SERVO_COUNT) {
				ESP_LOGE(TAG, "Invalid servo ID %u", servo_id);
				break;
			}
			cancel_servo_timeout(servo_id);
			int angle = cmd->cmd.drive_motor.angle;
			if (angle < 0) angle = 0;
			if (angle > 180) angle = 180;
			servo_set_angle(servo_id, (uint32_t)angle);
			servo_current_angle[servo_id] = (uint16_t)angle;
		} else if (cmd->cmd.drive_motor.motor_id == 1) {
			if (cmd->cmd.drive_motor.speed == 0) {
				motorA_stop();
				break;
			}
			uint8_t duty = speed_to_duty(cmd->cmd.drive_motor.speed);
			if (cmd->cmd.drive_motor.speed > 0) {
				motorA_forward(duty);
			} else {
				motorA_backward(duty);
			}
		} else if (cmd->cmd.drive_motor.motor_id == 2) {
			if (cmd->cmd.drive_motor.speed == 0) {
				motorB_stop();
				break;
			}
			uint8_t duty = speed_to_duty(cmd->cmd.drive_motor.speed);
			if (cmd->cmd.drive_motor.speed > 0) {
				motorB_forward(duty);
			} else {
				motorB_backward(duty);
			}
		} else {
			ESP_LOGE(TAG, "Invalid motor ID");
		}
		break;
	case CMD_STOP_MOTOR:
		ESP_LOGI(TAG, "stop motor %d", cmd->cmd.stop_motor.motor_id);
		if (cmd->cmd.stop_motor.motor_id == 1) {
			motorA_stop();
		} else if (cmd->cmd.stop_motor.motor_id == 2) {
			motorB_stop();
		} else {
			ESP_LOGE(TAG, "Invalid motor ID");
		}
		break;
	case CMD_STOP_ALL_MOTORS:
		ESP_LOGI(TAG, "Stop all motors command received");
		motorA_stop();
		motorB_stop();
		if (safety_timer) {
			esp_timer_stop(safety_timer);
		}
		for (uint8_t servo = 0; servo < PUPPY_SERVO_COUNT; ++servo) {
			cancel_servo_timeout(servo);
			servo_set_angle(servo, puppy_servo_boot_angle(servo));
			servo_current_angle[servo] = puppy_servo_boot_angle(servo);
		}
		break;
	case CMD_TURN_SERVO: {
		uint8_t servo_id = (uint8_t)cmd->cmd.turn_servo.servo_id;
		int angle = cmd->cmd.turn_servo.angle;
		int duration_ms = cmd->cmd.turn_servo.duration_ms;
		if (servo_id >= PUPPY_SERVO_COUNT) {
			ESP_LOGE(TAG, "Invalid servo ID %u", servo_id);
			break;
		}
		if (angle < 0) angle = 0;
		if (angle > 180) angle = 180;
		if (duration_ms < 0) duration_ms = 0;

		uint16_t previous_angle = servo_current_angle[servo_id];
		cancel_servo_timeout(servo_id);

		ESP_LOGI(TAG, "turn servo %u -> %d (timeout %d ms)", servo_id, angle,
		         duration_ms);

		servo_set_angle(servo_id, (uint32_t)angle);
		servo_current_angle[servo_id] = (uint16_t)angle;

		if (duration_ms > 0) {
			servo_timeout_state_t *state = &servo_timeouts[servo_id];
			if (state->timer == NULL) {
				ESP_LOGW(TAG, "No timer available for servo %u timeout", servo_id);
				break;
			}
			state->restore_angle = previous_angle;
			state->active = true;
			int64_t timeout_us = (int64_t)duration_ms * 1000;
			esp_err_t timer_result =
			    esp_timer_start_once(state->timer, timeout_us);
			if (timer_result != ESP_OK) {
				ESP_LOGW(TAG, "Failed to start servo timeout %u: %s", servo_id,
				         esp_err_to_name(timer_result));
				state->active = false;
			}
		}
		break;
	}
	}
}

void init_command_handler() {
	const esp_timer_create_args_t safety_timer_args = {
	    .callback = safety_timer_callback, .name = "safety_timer"};
	esp_err_t ret = esp_timer_create(&safety_timer_args, &safety_timer);
	if (ret != ESP_OK) {
		ESP_LOGE(TAG, "Failed to create safety timer: %s",
		         esp_err_to_name(ret));
	} else {
		ESP_LOGI(TAG, "Safety timer created successfully");
	}
	for (uint8_t servo = 0; servo < PUPPY_SERVO_COUNT; ++servo) {
		servo_timeout_state_t *state = &servo_timeouts[servo];
		servo_current_angle[servo] = puppy_servo_boot_angle(servo);
		state->restore_angle = servo_current_angle[servo];
		const esp_timer_create_args_t servo_timer_args = {
		    .callback = servo_timeout_callback,
		    .arg = (void *)(uintptr_t)servo,
		    .name = NULL,
		};
		esp_err_t timer_ret =
		    esp_timer_create(&servo_timer_args, &state->timer);
		if (timer_ret != ESP_OK) {
			ESP_LOGE(TAG,
			         "Failed to create servo timeout timer %u: %s", servo,
			         esp_err_to_name(timer_ret));
			state->timer = NULL;
		}
		state->active = false;
	}
}
