#include "command.h"
#include "esp_log.h"
#include "motor.h"
#include "esp_websocket_client.h"
#include "esp_timer.h"

#define TAG "COMMAND"

esp_timer_handle_t safety_timer;

void safety_timer_callback(void *arg) {
	ESP_LOGW(TAG, "Safety timeout: stopping all motors");
	motorA_stop();
	motorB_stop();
}

void handle_command(CommandPacket *cmd, esp_websocket_client_handle_t client) {
	switch (cmd->cmd_type) {
	case CMD_PING:
		ESP_LOGI(TAG, "Ping command received");
		char buff[] = {1, 0, MSG_TO_SRV_PONG};
		esp_websocket_client_send_bin(client, buff, sizeof(buff),
		                              portMAX_DELAY);
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
			servo_set_angle(cmd->cmd.drive_motor.angle);
		} else if (cmd->cmd.drive_motor.motor_id == 1) {
			if (cmd->cmd.drive_motor.speed > 0)
				motorA_forward(200);
			else
				motorA_backward(200);
		} else if (cmd->cmd.drive_motor.motor_id == 2) {
			if (cmd->cmd.drive_motor.speed > 0)
				motorB_forward(200);
			else
				motorB_backward(200);
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
		break;
	case CMD_TURN_SERVO:
		ESP_LOGI(TAG, "turn servo %d", cmd->cmd.turn_servo.angle);
		servo_set_angle(cmd->cmd.turn_servo.angle);
		break;
	}
}

void init_command_handler() {
	const esp_timer_create_args_t safety_timer_args = {
	    .callback = safety_timer_callback, .name = "safety_timer"};
	esp_err_t ret = esp_timer_create(&safety_timer_args, &safety_timer);
	if (ret != ESP_OK) {
		ESP_LOGE(TAG, "Failed to create safety timer: %s", esp_err_to_name(ret));
	} else {
		ESP_LOGI(TAG, "Safety timer created successfully");
	}
}