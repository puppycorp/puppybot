#include "esp_event.h"
#include "esp_websocket_client.h"
#include "../../src/protocol.h"

#define WS_SERVER "ws://" SERVER_HOST "/api/bot/1/ws"

esp_websocket_client_handle_t client;

void handle_command(CommandPacket *cmd) {
	switch (cmd->cmd_type) {
		case CMD_PING:
			ESP_LOGI(TAG, "Ping command received");
			char buff[] = {
				1,
				0,
				MSG_TO_SRV_TYPE
			};
			esp_websocket_client_send_bin(client, buff, sizeof(buff), portMAX_DELAY);
			break;
		case CMD_DRIVE_MOTOR:
			ESP_LOGI(TAG, "Drive motor command received");
			break;
		case CMD_STOP_MOTOR:
			ESP_LOGI(TAG, "Stop motor command received");
			break;
		case CMD_STOP_ALL_MOTORS:
			ESP_LOGI(TAG, "Stop all motors command received");
			break;
	}
}

void websocket_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

    switch (event_id) {
        case WEBSOCKET_EVENT_CONNECTED:
            ESP_LOGI(TAG, "WebSocket connected");
            break;
        case WEBSOCKET_EVENT_DISCONNECTED:
            ESP_LOGI(TAG, "WebSocket disconnected");
            break;
        case WEBSOCKET_EVENT_DATA:
            ESP_LOGI(TAG, "Received data: %.*s", data->data_len, (char *)data->data_ptr);
			CommandPacket cmd_packet;
			parse_cmd((uint8_t *)data->data_ptr, &cmd_packet);
			handle_command(&cmd_packet);
            break;
        case WEBSOCKET_EVENT_ERROR:
            ESP_LOGE(TAG, "WebSocket error");
			break;
    }
}

void websocket_app_start() {
	ESP_LOGI(TAG, "connecting to %s", WS_SERVER);
    esp_websocket_client_config_t websocket_cfg = {
        .uri = WS_SERVER
    };

    client = esp_websocket_client_init(&websocket_cfg);
    esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY, websocket_event_handler, NULL);
    esp_websocket_client_start(client);
}
