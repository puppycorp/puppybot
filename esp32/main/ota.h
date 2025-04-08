#include "esp_https_ota.h"

void ota_task(void *pvParameter) {
    ESP_LOGI(TAG, "Starting OTA...");
	ESP_LOGI(TAG, "Fetching OTA URL: %s", OTA_URL);

	esp_http_client_config_t http_config = {
        .url = OTA_URL,
        .event_handler = _http_event_handler,
        .transport_type = HTTP_TRANSPORT_OVER_TCP, // Force plain TCP (HTTP)
    };

	esp_https_ota_config_t ota_config = {
        .http_config = &http_config,
    };

    esp_err_t ret = esp_https_ota(&ota_config);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "OTA successful. Rebooting...");
        esp_restart();
    } else {
        ESP_LOGE(TAG, "OTA failed...");
    }

    vTaskDelete(NULL);
}