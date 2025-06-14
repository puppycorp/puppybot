#ifndef WIFI_H
#define WIFI_H

#include "esp_log.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_wifi.h"
#include <string.h>

#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif

#ifndef WIFI_PASS
#define WIFI_PASS ""
#endif

#ifndef WIFI_AP_SSID
#define WIFI_AP_SSID ""
#endif

#ifndef WIFI_AP_PASS
#define WIFI_AP_PASS ""
#endif

static const char *TAG = "WIFI";

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data) {
	if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
		esp_wifi_connect();
	} else if (event_base == WIFI_EVENT &&
	           event_id == WIFI_EVENT_STA_DISCONNECTED) {
		ESP_LOGI(TAG, "❌ Disconnected. Reconnecting...");
		esp_wifi_connect();
	} else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
		ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
		ESP_LOGI(TAG, "✅ Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
	}
}

void wifi_init_sta() {
	bool config_ok = true;
	if (WIFI_SSID[0] == '\0') {
		ESP_LOGW(TAG, "STA mode disabled: no SSID configured");
		config_ok = false;
	}
	if (WIFI_PASS[0] == '\0') {
		ESP_LOGW(TAG, "STA mode disabled: no password configured");
		config_ok = false;
	}
	if (!config_ok) {
		return;
	}

	esp_netif_init();
	esp_event_loop_create_default();
	esp_netif_create_default_wifi_sta();

	wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
	esp_wifi_init(&cfg);

	esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
	                           &wifi_event_handler, NULL);
	esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
	                           &wifi_event_handler, NULL);

	ESP_LOGI(TAG, "Connecting to WiFi SSID: %s", WIFI_SSID);
	ESP_LOGI(TAG, "Using password: %s", WIFI_PASS);

	wifi_config_t wifi_config = {
	    .sta =
	        {
	            .ssid = WIFI_SSID,
	            .password = WIFI_PASS,
	        },
	};

	esp_wifi_set_mode(WIFI_MODE_STA);
	esp_wifi_set_config(ESP_IF_WIFI_STA, &wifi_config);
	esp_wifi_start();

	ESP_LOGI(TAG, "Connecting to WiFi...");
	esp_wifi_connect();
}

/**
 * @brief Bring up ESP32 as a standalone Wi‑Fi Access Point (hot‑spot).
 *
 * Creates a soft‑AP with SSID `WIFI_AP_SSID` and password `WIFI_AP_PASS`.
 * Logs the assigned IP (192.168.4.1 by default) once started.
 */
void wifi_init_ap(void) {
	bool config_ok = true;
	if (WIFI_AP_SSID[0] == '\0') {
		ESP_LOGW(TAG, "AP mode disabled: no SSID configured");
		config_ok = false;
	}
	if (WIFI_AP_PASS[0] == '\0') {
		ESP_LOGW(TAG, "AP mode disabled: no password configured");
		config_ok = false;
	}
	if (!config_ok) {
		return;
	}

	esp_netif_init();
	esp_event_loop_create_default();
	esp_netif_create_default_wifi_ap();

	wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
	esp_wifi_init(&cfg);

	wifi_config_t ap_config = {
	    .ap = {.ssid = WIFI_AP_SSID,
	           .ssid_len = strlen(WIFI_AP_SSID),
	           .password = WIFI_AP_PASS,
	           .max_connection = 4,
	           .authmode = WIFI_AUTH_WPA_WPA2_PSK},
	};

	if (strlen(WIFI_AP_PASS) == 0) {
		ap_config.ap.authmode = WIFI_AUTH_OPEN;
	}

	esp_wifi_set_mode(WIFI_MODE_AP);
	esp_wifi_set_config(ESP_IF_WIFI_AP, &ap_config);
	esp_wifi_start();

	ESP_LOGI(TAG, "🚀 Soft‑AP started. SSID: %s  PASS: %s", WIFI_AP_SSID,
	         WIFI_AP_PASS);
}

#endif // WIFI_H