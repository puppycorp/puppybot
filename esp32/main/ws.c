#include "ws.h"
#include "esp_log.h"
#include "esp_websocket_client.h"
#include <string.h>
// #include "wss_server.h"

#if defined(SERVER_HOST) && defined(DEVICE_ID)
#define WS_SERVER "ws://" SERVER_HOST "/api/bot/" DEVICE_ID "/ws"
#elif defined(SERVER_HOST)
#define WS_SERVER "ws://" SERVER_HOST "/api/bot/1/ws"
#endif

esp_websocket_client_handle_t client;
httpd_handle_t ws_server = NULL;
static esp_timer_handle_t heartbeat_timer;
static bool websocket_connected = false;

#define TAG "WEBSOCKET"
#define HEARTBEAT_INTERVAL_MS 30000  // 30 seconds

/* ---------------------------------------------------------------------------
 * WebSocket client heartbeat and reconnection logic
 * -------------------------------------------------------------------------*/

static void websocket_reconnect(void) {
    if (client && !websocket_connected) {
        ESP_LOGI(TAG, "Attempting WebSocket reconnection...");
        esp_websocket_client_stop(client);
        vTaskDelay(pdMS_TO_TICKS(2000)); // Wait 2 seconds before reconnecting
        esp_websocket_client_start(client);
    }
}

static void heartbeat_timer_callback(void *arg) {
    if (websocket_connected && client) {
        ESP_LOGI(TAG, "Sending heartbeat ping");
        esp_err_t err = esp_websocket_client_send_text(client, "ping", 4, portMAX_DELAY);
        ESP_LOGI(TAG, "heartbeat ping result: %s", esp_err_to_name(err));
        /*if (err != ESP_OK) {
            ESP_LOGE(TAG, "Failed to send heartbeat: %s", esp_err_to_name(err));
            websocket_connected = false;
            esp_timer_stop(heartbeat_timer);
            websocket_reconnect();
        }*/
    }
}

/* ---------------------------------------------------------------------------
 * Built‑in WebSocket server support
 * -------------------------------------------------------------------------*/
static esp_err_t ws_httpd_handler(httpd_req_t *req)
{
    /* For the initial handshake we only need to return OK */
    if (req->method == HTTP_GET) {
        ESP_LOGI(TAG, "WebSocket handshake completed");
        return ESP_OK;
    }

    /* Prepare to receive the WebSocket frame */
    httpd_ws_frame_t ws_pkt;
    memset(&ws_pkt, 0, sizeof(ws_pkt));
    ws_pkt.type = HTTPD_WS_TYPE_BINARY;

    /* First call to learn payload length */
    esp_err_t ret = httpd_ws_recv_frame(req, &ws_pkt, 0);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to get WS frame length: %d", ret);
        return ret;
    }
	ESP_LOGI(TAG, "frame len is %d", ws_pkt.len);

    uint8_t *payload = (uint8_t *)malloc(ws_pkt.len);
    if (!payload) {
        ESP_LOGE(TAG, "Out of memory for WS payload");
        return ESP_ERR_NO_MEM;
    }
    ws_pkt.payload = payload;

	if (ws_pkt.type == HTTPD_WS_TYPE_PONG) {
        free(payload);
        // return wss_keep_alive_client_is_active(httpd_get_global_user_ctx(req->handle),
        //         httpd_req_to_sockfd(req));
		return ESP_OK;
    } else if (ws_pkt.type == HTTPD_WS_TYPE_BINARY) {
        // Receive full binary payload and process as command
        ret = httpd_ws_recv_frame(req, &ws_pkt, ws_pkt.len);
        if (ret == ESP_OK) {
            CommandPacket cmd_packet;
            parse_cmd(ws_pkt.payload, &cmd_packet);
            handle_command(&cmd_packet, client);
        } else {
            ESP_LOGE(TAG, "Failed to receive binary WS frame: %d", ret);
        }
        free(payload);
        return ret;
    } else if (ws_pkt.type == HTTPD_WS_TYPE_TEXT || ws_pkt.type == HTTPD_WS_TYPE_PING || ws_pkt.type == HTTPD_WS_TYPE_CLOSE) {
        if (ws_pkt.type == HTTPD_WS_TYPE_TEXT) {
            ESP_LOGI(TAG, "Received packet with message: %s", ws_pkt.payload);
        } else if (ws_pkt.type == HTTPD_WS_TYPE_PING) {
            // Response PONG packet to peer
            ESP_LOGI(TAG, "Got a WS PING frame, Replying PONG");
            ws_pkt.type = HTTPD_WS_TYPE_PONG;
        } else if (ws_pkt.type == HTTPD_WS_TYPE_CLOSE) {
            // Response CLOSE packet with no payload to peer
            ws_pkt.len = 0;
            ws_pkt.payload = NULL;
        }
        ret = httpd_ws_send_frame(req, &ws_pkt);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "httpd_ws_send_frame failed with %d", ret);
        }
        ESP_LOGI(TAG, "ws_handler: httpd_handle_t=%p, sockfd=%d, client_info:%d", req->handle,
                 httpd_req_to_sockfd(req), httpd_ws_get_fd_info(req->handle, httpd_req_to_sockfd(req)));
        free(payload);
        return ret;
    }


    /* Receive the full frame payload */
    ret = httpd_ws_recv_frame(req, &ws_pkt, ws_pkt.len);
    if (ret == ESP_OK) {
        CommandPacket cmd_packet;
        parse_cmd(ws_pkt.payload, &cmd_packet);
        handle_command(&cmd_packet, client);   /* Re‑use existing command handler */
    } else {
        ESP_LOGE(TAG, "Failed to receive WS frame: %d", ret);
    }

    free(payload);
    return ret;
}

/* URI handler for the bot control endpoint */
static const httpd_uri_t ws_uri_handler = {
    .uri         = "/ws",
    .method      = HTTP_GET,
    .handler     = ws_httpd_handler,
    .user_ctx    = NULL,
#if CONFIG_HTTPD_WS_SUPPORT
    .is_websocket = true,
#endif
};

/* Start the HTTP‑based WebSocket server */
static void websocket_server_start(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();

    esp_err_t ret = httpd_start(&ws_server, &config);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "WebSocket server started on port %d", config.server_port);
        httpd_register_uri_handler(ws_server, &ws_uri_handler);
    } else {
        ESP_LOGE(TAG, "Failed to start WebSocket server: %d", ret);
    }
}

void websocket_event_handler(void *handler_args, esp_event_base_t base,
                             int32_t event_id, void *event_data) {
	esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

	switch (event_id) {
	case WEBSOCKET_EVENT_CONNECTED:
		ESP_LOGI(TAG, "WebSocket connected");
		websocket_connected = true;
		// Start heartbeat timer
		if (heartbeat_timer) {
			esp_timer_start_periodic(heartbeat_timer, HEARTBEAT_INTERVAL_MS * 1000);
		}
		break;
	case WEBSOCKET_EVENT_DISCONNECTED:
		ESP_LOGI(TAG, "WebSocket disconnected");
		websocket_connected = false;
		// Stop heartbeat timer
		if (heartbeat_timer) {
			esp_timer_stop(heartbeat_timer);
		}
		// Schedule reconnection attempt
		vTaskDelay(pdMS_TO_TICKS(1000));
		websocket_reconnect();
		break;
	case WEBSOCKET_EVENT_DATA:
		ESP_LOGI(TAG, "Received data: %.*s", data->data_len, (char *)data->data_ptr);
		// Handle pong responses or ignore ping/pong messages
		if (data->data_len == 4 && strncmp((char*)data->data_ptr, "pong", 4) == 0) {
			ESP_LOGI(TAG, "Received heartbeat pong");
			break;
		}
		if (data->data_len == 4 && strncmp((char*)data->data_ptr, "ping", 4) == 0) {
			ESP_LOGI(TAG, "Received ping, ignoring");
			break;
		}
		// Parse and handle command
		CommandPacket cmd_packet;
		parse_cmd((uint8_t *)data->data_ptr, &cmd_packet);
		handle_command(&cmd_packet, client);
		break;
	case WEBSOCKET_EVENT_ERROR:
		ESP_LOGE(TAG, "WebSocket error");
		websocket_connected = false;
		// Stop heartbeat timer
		if (heartbeat_timer) {
			esp_timer_stop(heartbeat_timer);
		}
		// Schedule reconnection attempt
		vTaskDelay(pdMS_TO_TICKS(2000));
		websocket_reconnect();
		break;
	}
}

/* ---------------------------------------------------------------------------
 * WebSocket status and utility functions
 * -------------------------------------------------------------------------*/

bool is_websocket_connected(void) {
    return websocket_connected;
}

void websocket_send_status(void) {
    if (websocket_connected && client) {
        const char* status_msg = "status_ok";
        esp_err_t err = esp_websocket_client_send_text(client, status_msg, strlen(status_msg), portMAX_DELAY);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Failed to send status: %s", esp_err_to_name(err));
            websocket_connected = false;
        }
    }
}

void websocket_app_start() {
#ifndef SERVER_HOST
	ESP_LOGW(TAG,
	         "SERVER_HOST not defined, skipping websocket initialization");
	return;
#endif
#ifdef SERVER_HOST
	ESP_LOGI(TAG, "SERVER_HOST defined, initializing websocket");
	ESP_LOGI(TAG, "connecting to %s", WS_SERVER);
	
	// Create heartbeat timer
	const esp_timer_create_args_t heartbeat_timer_args = {
		.callback = heartbeat_timer_callback,
		.name = "websocket_heartbeat"
	};
	esp_err_t ret = esp_timer_create(&heartbeat_timer_args, &heartbeat_timer);
	if (ret != ESP_OK) {
		ESP_LOGE(TAG, "Failed to create heartbeat timer: %s", esp_err_to_name(ret));
	}
	
	esp_websocket_client_config_t websocket_cfg = {
		.uri = WS_SERVER,
		.reconnect_timeout_ms = 10000,  // 10 second reconnect timeout
		.network_timeout_ms = 10000,    // 10 second network timeout
	};

	client = esp_websocket_client_init(&websocket_cfg);
	if (client == NULL) {
		ESP_LOGE(TAG, "Failed to initialize WebSocket client");
		return;
	}
	
	esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY,
	                              websocket_event_handler, NULL);
	                              
	ret = esp_websocket_client_start(client);
	if (ret != ESP_OK) {
		ESP_LOGE(TAG, "Failed to start WebSocket client: %s", esp_err_to_name(ret));
	}
#endif
    /* Always start our built‑in WebSocket server so others can connect */
    //websocket_server_start();
}
