#include "esp_event.h"
#include "esp_websocket_client.h"

void websocket_event_handler(void *handler_args, esp_event_base_t base, int32_t event_id, void *event_data) {
    esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

    switch (event_id) {
        case WEBSOCKET_EVENT_CONNECTED:
            ESP_LOGI(TAG, "✅ WebSocket connected");
            esp_websocket_client_send_text(client, "Hello Server", strlen("Hello Server"), portMAX_DELAY);
            break;
        case WEBSOCKET_EVENT_DISCONNECTED:
            ESP_LOGI(TAG, "❌ WebSocket disconnected");
            break;
        case WEBSOCKET_EVENT_DATA:
            ESP_LOGI(TAG, "📩 Received data: %.*s", data->data_len, (char *)data->data_ptr);
            break;
        case WEBSOCKET_EVENT_ERROR:
            ESP_LOGE(TAG, "⚠️ WebSocket error");
            break;
    }
}

void websocket_app_start() {
    esp_websocket_client_config_t websocket_cfg = {
        .uri = "ws://10.70.2.56:8080"
    };

    client = esp_websocket_client_init(&websocket_cfg);
    esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY, websocket_event_handler, NULL);
    esp_websocket_client_start(client);
}
