#ifndef WS_H
#define WS_H

#include "../../src/protocol.h"
#include "esp_event.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "motor.h"
#if defined(SERVER_HOST)
#define WS_SERVER "ws://" SERVER_HOST "/api/bot/1/ws"
#endif

esp_websocket_client_handle_t client;
esp_timer_handle_t safety_timer;

#define WS_LOG_TAG "WEBSOCKET"

void handle_command(CommandPacket *cmd) {
	switch (cmd->cmd_type) {
	case CMD_PING:
		ESP_LOGI(WS_LOG_TAG, "Ping command received");
		char buff[] = {1, 0, MSG_TO_SRV_TYPE};
		esp_websocket_client_send_bin(client, buff, sizeof(buff),
		                              portMAX_DELAY);
		break;
	case CMD_DRIVE_MOTOR:
		ESP_LOGI(WS_LOG_TAG, "drive motor %d with speed %d",
		         cmd->cmd.drive_motor.motor_id, cmd->cmd.drive_motor.speed);
		// Reset the safety timer
		esp_timer_stop(safety_timer);
		esp_timer_start_once(safety_timer, 1000000);
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
			ESP_LOGE(WS_LOG_TAG, "Invalid motor ID");
		}
		break;
	case CMD_STOP_MOTOR:
		ESP_LOGI(WS_LOG_TAG, "stop motor %d", cmd->cmd.stop_motor.motor_id);
		if (cmd->cmd.stop_motor.motor_id == 1) {
			motorA_stop();
		} else if (cmd->cmd.stop_motor.motor_id == 2) {
			motorB_stop();
		} else {
			ESP_LOGE(WS_LOG_TAG, "Invalid motor ID");
		}
		break;
	case CMD_STOP_ALL_MOTORS:
		ESP_LOGI(WS_LOG_TAG, "Stop all motors command received");
		motorA_stop();
		motorB_stop();
		break;
	case CMD_TURN_SERVO:
		ESP_LOGI(WS_LOG_TAG, "turn servo %d", cmd->cmd.turn_servo.angle);
		servo_set_angle(cmd->cmd.turn_servo.angle);
		break;
	}
}

void safety_timer_callback(void *arg) {
	ESP_LOGW(WS_LOG_TAG, "Safety timeout: stopping all motors");
	motorA_stop();
	motorB_stop();
}

void websocket_event_handler(void *handler_args, esp_event_base_t base,
                             int32_t event_id, void *event_data) {
	esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

	switch (event_id) {
	case WEBSOCKET_EVENT_CONNECTED:
		ESP_LOGI(WS_LOG_TAG, "WebSocket connected");
		break;
	case WEBSOCKET_EVENT_DISCONNECTED:
		ESP_LOGI(WS_LOG_TAG, "WebSocket disconnected");
		break;
	case WEBSOCKET_EVENT_DATA:
		ESP_LOGI(WS_LOG_TAG, "Received data: %.*s", data->data_len,
		         (char *)data->data_ptr);
		CommandPacket cmd_packet;
		parse_cmd((uint8_t *)data->data_ptr, &cmd_packet);
		handle_command(&cmd_packet);
		break;
	case WEBSOCKET_EVENT_ERROR:
		ESP_LOGE(WS_LOG_TAG, "WebSocket error");
		break;
	}
}

void websocket_app_start() {
#ifndef SERVER_HOST
	ESP_LOGW(WS_LOG_TAG, "SERVER_HOST not defined, skipping websocket initialization");
	return;
#endif
#ifdef SERVER_HOST
	ESP_LOGI(WS_LOG_TAG, "SERVER_HOST defined, initializing websocket");
	ESP_LOGI(WS_LOG_TAG, "connecting to %s", WS_SERVER);
	esp_websocket_client_config_t websocket_cfg = {.uri = WS_SERVER};

	client = esp_websocket_client_init(&websocket_cfg);
	esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY,
	                              websocket_event_handler, NULL);
	esp_websocket_client_start(client);

	// Create the safety timer
	const esp_timer_create_args_t safety_timer_args = {
	    .callback = safety_timer_callback, .name = "safety_timer"};
	ESP_ERROR_CHECK(esp_timer_create(&safety_timer_args, &safety_timer));
	// Start the safety timer (1 second = 1,000,000 microseconds)
	ESP_ERROR_CHECK(esp_timer_start_once(safety_timer, 1000000));
#endif
}

#endif // WS_H