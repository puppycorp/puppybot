#include "mdns.h"
#include "variant_config.h"

int mdns_service_init(void) {
	esp_err_t ret = mdns_init();
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to initialize mDNS: %s", esp_err_to_name(ret));
		return -1;
	}

	ret = mdns_hostname_set(PUPPY_HOSTNAME);
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to set hostname: %s", esp_err_to_name(ret));
		return -1;
	}

	ret = mdns_instance_name_set(PUPPY_INSTANCE_NAME);
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to set instance name: %s",
		         esp_err_to_name(ret));
		return -1;
	}

	ret = mdns_service_add(PUPPY_HOSTNAME, "_ws", "_tcp", 80, NULL, 0);
	if (ret != ESP_OK) {
		ESP_LOGE("MDNS", "Failed to add service: %s", esp_err_to_name(ret));
		return -1;
	}

	char hostname_alias[32];
	snprintf(hostname_alias, sizeof(hostname_alias), "%s_1", PUPPY_HOSTNAME);
	mdns_hostname_set(hostname_alias);
	mdns_instance_name_set(PUPPY_INSTANCE_NAME);
	return 0;
}