#ifndef WIFI_H
#define WIFI_H

#include "esp_log.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_wifi.h"
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#ifndef WIFI_CREDENTIALS
#define WIFI_CREDENTIALS ""
#endif

#ifndef WIFI_AP_SSID
#define WIFI_AP_SSID ""
#endif

#ifndef WIFI_AP_PASS
#define WIFI_AP_PASS ""
#endif

static const char *TAG = "WIFI";

#define MAX_WIFI_CREDENTIALS 5

typedef struct {
	char ssid[33];
	char password[65];
} wifi_credential_t;

static wifi_credential_t wifi_credentials[MAX_WIFI_CREDENTIALS];
static size_t wifi_credential_count = 0;
static size_t wifi_current_credential = 0;
static wifi_config_t wifi_config;

static void wifi_copy_string(char *dest, size_t dest_size, const char *src) {
	if (dest_size == 0) {
		return;
	}
	if (src == NULL) {
		src = "";
	}
	strncpy(dest, src, dest_size - 1);
	dest[dest_size - 1] = '\0';
}

static char *wifi_trim_whitespace(char *str) {
	while (*str && isspace((unsigned char)*str)) {
		str++;
	}
	if (*str == '\0') {
		return str;
	}
	char *end = str + strlen(str) - 1;
	while (end > str && isspace((unsigned char)*end)) {
		*end-- = '\0';
	}
	if (isspace((unsigned char)*end)) {
		*end = '\0';
	}
	return str;
}

static void wifi_add_credential(const char *ssid, const char *password) {
	if (ssid == NULL || ssid[0] == '\0') {
		ESP_LOGW(TAG, "Skipping WiFi credential with empty SSID");
		return;
	}
	if (wifi_credential_count >= MAX_WIFI_CREDENTIALS) {
		ESP_LOGW(TAG,
		         "Maximum WiFi credentials reached (%d). Ignoring additional "
		         "entries.",
		         MAX_WIFI_CREDENTIALS);
		return;
	}

	wifi_copy_string(wifi_credentials[wifi_credential_count].ssid,
	                 sizeof(wifi_credentials[wifi_credential_count].ssid),
	                 ssid);
	wifi_copy_string(wifi_credentials[wifi_credential_count].password,
	                 sizeof(wifi_credentials[wifi_credential_count].password),
	                 password);

	ESP_LOGI(TAG, "Loaded WiFi credential %d: SSID=%s",
	         (int)(wifi_credential_count + 1),
	         wifi_credentials[wifi_credential_count].ssid);
	wifi_credential_count++;
}

static void wifi_parse_credentials_string(char *credentials) {
	char *context = NULL;
	char *pair = strtok_r(credentials, ";", &context);
	while (pair != NULL) {
		char *trimmed_pair = wifi_trim_whitespace(pair);
		if (*trimmed_pair == '\0') {
			pair = strtok_r(NULL, ";", &context);
			continue;
		}

		char *separator = strchr(trimmed_pair, ':');
		if (separator == NULL) {
			ESP_LOGW(TAG, "Skipping WiFi credential without ':' separator: %s",
			         trimmed_pair);
			pair = strtok_r(NULL, ";", &context);
			continue;
		}

		*separator = '\0';
		char *ssid = wifi_trim_whitespace(trimmed_pair);
		char *password = wifi_trim_whitespace(separator + 1);

		wifi_add_credential(ssid, password);
		pair = strtok_r(NULL, ";", &context);
	}
}

static void wifi_load_credentials(void) {
	wifi_credential_count = 0;
	memset(wifi_credentials, 0, sizeof(wifi_credentials));

	if (WIFI_CREDENTIALS[0] != '\0') {
		char *credential_buffer = strdup(WIFI_CREDENTIALS);
		if (credential_buffer == NULL) {
			ESP_LOGE(TAG,
			         "Failed to allocate memory for WiFi credentials list");
		} else {
			wifi_parse_credentials_string(credential_buffer);
			free(credential_buffer);
		}
	}

	if (wifi_credential_count == 0) {
		ESP_LOGW(TAG, "STA mode disabled: no WiFi credentials configured");
	}
}

static void wifi_prepare_current_credential(void) {
	if (wifi_credential_count == 0) {
		return;
	}

	const wifi_credential_t *cred = &wifi_credentials[wifi_current_credential];
	memset(&wifi_config, 0, sizeof(wifi_config));
	wifi_copy_string((char *)wifi_config.sta.ssid, sizeof(wifi_config.sta.ssid),
	                 cred->ssid);
	wifi_copy_string((char *)wifi_config.sta.password,
	                 sizeof(wifi_config.sta.password), cred->password);
	esp_wifi_set_config(WIFI_IF_STA, &wifi_config);

	ESP_LOGI(TAG, "Configured WiFi credential %d/%d (SSID: %s)",
	         (int)(wifi_current_credential + 1), (int)wifi_credential_count,
	         cred->ssid);
}

static void wifi_advance_to_next_credential(void) {
	if (wifi_credential_count == 0) {
		return;
	}

	wifi_current_credential =
	    (wifi_current_credential + 1) % wifi_credential_count;
}

static void wifi_connect_current_credential(void) {
	if (wifi_credential_count == 0) {
		ESP_LOGW(TAG,
		         "Cannot connect to WiFi: no credentials available. Configure "
		         "WIFI_CREDENTIALS.");
		return;
	}

	wifi_prepare_current_credential();
	ESP_LOGI(TAG, "Connecting to WiFi using SSID: %s",
	         wifi_credentials[wifi_current_credential].ssid);
	esp_wifi_connect();
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data) {
	if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
		wifi_connect_current_credential();
	} else if (event_base == WIFI_EVENT &&
	           event_id == WIFI_EVENT_STA_DISCONNECTED) {
		wifi_event_sta_disconnected_t *event =
		    (wifi_event_sta_disconnected_t *)event_data;
		const wifi_credential_t *cred =
		    wifi_credentials + wifi_current_credential;
		ESP_LOGW(TAG,
		         "❌ Disconnected from SSID %s (reason: %d). Trying next "
		         "credential...",
		         cred->ssid, event ? event->reason : -1);

		size_t previous_index = wifi_current_credential;
		wifi_advance_to_next_credential();

		if (wifi_credential_count > 1 && wifi_current_credential == 0 &&
		    previous_index != 0) {
			ESP_LOGW(TAG, "All configured WiFi credentials failed. Restarting "
			              "from the first entry.");
		} else if (wifi_credential_count == 1) {
			ESP_LOGW(TAG, "Only one WiFi credential configured. Retrying the "
			              "same SSID.");
		}

		wifi_connect_current_credential();
	} else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
		ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
		ESP_LOGI(TAG, "✅ Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
	}
}

void wifi_init_sta() {
	wifi_load_credentials();
	if (wifi_credential_count == 0) {
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

	esp_wifi_set_mode(WIFI_MODE_STA);
	esp_wifi_set_ps(WIFI_PS_NONE);
	wifi_current_credential = 0;
	wifi_prepare_current_credential();
	esp_wifi_start();
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
	esp_wifi_set_config(WIFI_IF_AP, &ap_config);
	esp_wifi_start();

	ESP_LOGI(TAG, "🚀 Soft‑AP started. SSID: %s  PASS: %s", WIFI_AP_SSID,
	         WIFI_AP_PASS);
}

int wifi_init(void) {
	wifi_init_sta();
	return 0;
}

#endif // WIFI_H
