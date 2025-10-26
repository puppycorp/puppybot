#include "../../src/comm.h"
#include "esp_websocket_client.h"

#define MSG_TO_SRV_PONG 0x01

int send_pong(void *client) {
	if (!client) {
		return -1;
	}

	esp_websocket_client_handle_t ws_client =
	    (esp_websocket_client_handle_t)client;
	char buff[] = {1, 0, MSG_TO_SRV_PONG};
	int ret = esp_websocket_client_send_bin(ws_client, buff, sizeof(buff),
	                                        portMAX_DELAY);
	return ret >= 0 ? 0 : -1;
}
