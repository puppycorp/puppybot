#include "ws.h"
#include "../../src/protocol.h"
#include "esp_log.h"
#include "esp_app_desc.h"
#include "esp_websocket_client.h"
#include "variant_config.h"
#include <stdlib.h>
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

static void websocket_send_my_info(void) {
        if (!client) {
                return;
        }

        const esp_app_desc_t *app_desc = esp_app_get_description();
        const char *fw_version = app_desc ? app_desc->version : "unknown";
        const char *variant = PUPPY_INSTANCE_NAME;

        size_t version_len = strlen(fw_version);
        if (version_len > 255) {
                version_len = 255;
        }
        size_t variant_len = strlen(variant);
        if (variant_len > 255) {
                variant_len = 255;
        }

        const size_t total_len = 3 + 1 + version_len + 1 + variant_len;
        uint8_t *payload = (uint8_t *)malloc(total_len);
        if (!payload) {
                ESP_LOGE(TAG, "Failed to allocate buffer for MyInfo message");
                return;
        }

        size_t offset = 0;
        payload[offset++] = (uint8_t)(PUPPY_PROTOCOL_VERSION & 0xff);
        payload[offset++] = (uint8_t)((PUPPY_PROTOCOL_VERSION >> 8) & 0xff);
        payload[offset++] = MSG_TO_SRV_MY_INFO;
        payload[offset++] = (uint8_t)version_len;
        memcpy(&payload[offset], fw_version, version_len);
        offset += version_len;
        payload[offset++] = (uint8_t)variant_len;
        memcpy(&payload[offset], variant, variant_len);
        offset += variant_len;

        esp_err_t err = esp_websocket_client_send_bin(
                client,
                (const char *)payload,
                offset,
                portMAX_DELAY);
        if (err != ESP_OK) {
                ESP_LOGE(TAG, "Failed to send MyInfo message: %s", esp_err_to_name(err));
        } else {
                ESP_LOGI(TAG, "Sent MyInfo (fw=%.*s, variant=%.*s)", (int)version_len, fw_version, (int)variant_len, variant);
        }

        free(payload);
}

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

#if defined(__GNUC__)
static void __attribute__((unused)) heartbeat_timer_callback(void *arg) {
#else
static void heartbeat_timer_callback(void *arg) {
#endif
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
    if (req->method == HTTP_GET) {
        ESP_LOGI(TAG, "WebSocket server handshake completed");
        return ESP_OK;
    }

    httpd_ws_frame_t ws_pkt;
    memset(&ws_pkt, 0, sizeof(ws_pkt));
    ws_pkt.type = HTTPD_WS_TYPE_BINARY;

    esp_err_t ret = httpd_ws_recv_frame(req, &ws_pkt, 0);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to get WS frame length: %s", esp_err_to_name(ret));
        return ret;
    }

    if (ws_pkt.len > 0) {
        ws_pkt.payload = (uint8_t *)malloc(ws_pkt.len + 1);
        if (ws_pkt.payload == NULL) {
            ESP_LOGE(TAG, "Out of memory for WS payload len=%zu", ws_pkt.len);
            return ESP_ERR_NO_MEM;
        }
    }

    ret = httpd_ws_recv_frame(req, &ws_pkt, ws_pkt.len);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to receive WS frame: %s", esp_err_to_name(ret));
        free(ws_pkt.payload);
        return ret;
    }

    if (ws_pkt.payload && ws_pkt.type == HTTPD_WS_TYPE_TEXT) {
        ((uint8_t *)ws_pkt.payload)[ws_pkt.len] = '\0';
    }

    switch (ws_pkt.type) {
    case HTTPD_WS_TYPE_BINARY:
        if (ws_pkt.len < 4) {
            ESP_LOGW(TAG, "Ignoring short binary frame len=%zu", ws_pkt.len);
            break;
        }
        ESP_LOGI(TAG, "Processing binary frame len=%zu", ws_pkt.len);
        CommandPacket cmd_packet;
        parse_cmd(ws_pkt.payload, &cmd_packet);
        handle_command(&cmd_packet, NULL);

        if (cmd_packet.cmd_type == CMD_PING) {
            const uint8_t pong_payload[] = {1, 0, MSG_TO_SRV_PONG};
            httpd_ws_frame_t pong_frame = {
                .final = true,
                .fragmented = false,
                .type = HTTPD_WS_TYPE_BINARY,
                .payload = (uint8_t *)pong_payload,
                .len = sizeof(pong_payload),
            };
            ret = httpd_ws_send_frame(req, &pong_frame);
            if (ret != ESP_OK) {
                ESP_LOGE(TAG, "Failed to send protocol pong: %s", esp_err_to_name(ret));
            }
        }
        break;
    case HTTPD_WS_TYPE_TEXT:
        ESP_LOGI(TAG, "WS text frame: %s", ws_pkt.payload ? (char *)ws_pkt.payload : "<empty>");
        break;
    case HTTPD_WS_TYPE_PING: {
        ESP_LOGI(TAG, "WS ping frame received, replying pong");
        httpd_ws_frame_t pong_frame = ws_pkt;
        pong_frame.type = HTTPD_WS_TYPE_PONG;
        ret = httpd_ws_send_frame(req, &pong_frame);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "Failed to send WS pong: %s", esp_err_to_name(ret));
        }
        break;
    }
    case HTTPD_WS_TYPE_PONG:
        ESP_LOGI(TAG, "WS pong frame received");
        break;
    case HTTPD_WS_TYPE_CLOSE: {
        ESP_LOGI(TAG, "WS close frame received, acknowledging");
        httpd_ws_frame_t close_frame = {
            .final = true,
            .fragmented = false,
            .type = HTTPD_WS_TYPE_CLOSE,
            .payload = NULL,
            .len = 0,
        };
        ret = httpd_ws_send_frame(req, &close_frame);
        if (ret != ESP_OK) {
            ESP_LOGE(TAG, "Failed to acknowledge close frame: %s", esp_err_to_name(ret));
        }
        break;
    }
    default:
        ESP_LOGW(TAG, "Unhandled WS frame type %d", ws_pkt.type);
        break;
    }

    free(ws_pkt.payload);
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
    if (ws_server != NULL) {
        ESP_LOGI(TAG, "WebSocket server already running");
        return;
    }

    httpd_config_t config = HTTPD_DEFAULT_CONFIG();

    esp_err_t ret = httpd_start(&ws_server, &config);
    if (ret == ESP_OK) {
        ESP_LOGI(TAG, "WebSocket server started on port %d", config.server_port);
        httpd_register_uri_handler(ws_server, &ws_uri_handler);
    } else {
        ESP_LOGE(TAG, "Failed to start WebSocket server: %s", esp_err_to_name(ret));
        ws_server = NULL;
    }
}

void websocket_event_handler(void *handler_args, esp_event_base_t base,
                             int32_t event_id, void *event_data) {
	esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

        switch (event_id) {
        case WEBSOCKET_EVENT_CONNECTED:
                ESP_LOGI(TAG, "WebSocket connected");
                websocket_connected = true;
                websocket_send_my_info();
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
    websocket_server_start();

#ifndef SERVER_HOST
	ESP_LOGW(TAG,
	         "SERVER_HOST not defined, skipping outbound websocket initialization");
	return;
#else
	ESP_LOGI(TAG, "SERVER_HOST defined, initializing websocket");
	ESP_LOGI(TAG, "connecting to %s", WS_SERVER);
	
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
		.reconnect_timeout_ms = 10000,
		.network_timeout_ms = 10000,
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
}
