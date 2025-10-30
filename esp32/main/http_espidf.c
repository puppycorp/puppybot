#ifdef ESP_PLATFORM

#include "../../src/http.h"
#include "../../src/log.h"
#include "../../src/platform.h"

#include <esp_http_server.h>
#include <esp_websocket_client.h>
#include <stdlib.h>
#include <string.h>

static const char *TAG = "http_espidf";

// ============================================================================
// ESP-IDF HTTP Server Implementation
// ============================================================================

struct http_server {
	httpd_handle_t handle;
};

http_server *http_server_init() {
	http_server *server = malloc(sizeof(http_server));
	if (!server) {
		log_error(TAG, "Failed to allocate server");
		return NULL;
	}

	httpd_config_t config = HTTPD_DEFAULT_CONFIG();
	config.max_open_sockets = 7;

	esp_err_t ret = httpd_start(&server->handle, &config);
	if (ret != ESP_OK) {
		log_error(TAG, "Failed to start HTTP server: %s", esp_err_to_name(ret));
		free(server);
		return NULL;
	}

	log_info(TAG, "HTTP server started");
	return server;
}

// Internal wrapper to call the platform-independent handler
static esp_err_t espidf_ws_handler_wrapper(httpd_req_t *req) {
	http_req wrapped_req = {.method =
	                            (req->method == HTTP_GET) ? HTTP_METHOD_GET : 0,
	                        .platform_ctx = req};

	int result = ws_httpd_handler(&wrapped_req);
	return (result == 0) ? ESP_OK : ESP_FAIL;
}

void http_register_handler(http_server *server, const http_route *handler) {
	if (!server || !handler) {
		log_error(TAG, "Invalid server or handler");
		return;
	}

	httpd_uri_t uri = {
	    .uri = handler->path,
	    .method = (handler->method == HTTP_METHOD_GET) ? HTTP_GET : HTTP_POST,
	    .handler = espidf_ws_handler_wrapper,
	    .user_ctx = handler->ctx,
	    .is_websocket = true,
	    .handle_ws_control_frames = false};

	esp_err_t ret = httpd_register_uri_handler(server->handle, &uri);
	if (ret != ESP_OK) {
		log_error(TAG, "Failed to register handler for %s: %s", handler->path,
		          esp_err_to_name(ret));
	} else {
		log_info(TAG, "Registered handler for %s", handler->path);
	}
}

// ============================================================================
// WebSocket Frame Send/Receive Implementation
// ============================================================================

static ws_frame_type_t espidf_to_ws_frame_type(httpd_ws_type_t type) {
	switch (type) {
	case HTTPD_WS_TYPE_TEXT:
		return WS_FRAME_TEXT;
	case HTTPD_WS_TYPE_BINARY:
		return WS_FRAME_BINARY;
	case HTTPD_WS_TYPE_CLOSE:
		return WS_FRAME_CLOSE;
	case HTTPD_WS_TYPE_PING:
		return WS_FRAME_PING;
	case HTTPD_WS_TYPE_PONG:
		return WS_FRAME_PONG;
	default:
		return WS_FRAME_BINARY;
	}
}

static httpd_ws_type_t ws_to_espidf_frame_type(ws_frame_type_t type) {
	switch (type) {
	case WS_FRAME_TEXT:
		return HTTPD_WS_TYPE_TEXT;
	case WS_FRAME_BINARY:
		return HTTPD_WS_TYPE_BINARY;
	case WS_FRAME_CLOSE:
		return HTTPD_WS_TYPE_CLOSE;
	case WS_FRAME_PING:
		return HTTPD_WS_TYPE_PING;
	case WS_FRAME_PONG:
		return HTTPD_WS_TYPE_PONG;
	default:
		return HTTPD_WS_TYPE_BINARY;
	}
}

int http_ws_recv_frame(http_req *req, ws_frame *frame, size_t max_len) {
	if (!req || !frame || !req->platform_ctx) {
		return -1;
	}

	httpd_req_t *espidf_req = (httpd_req_t *)req->platform_ctx;

	httpd_ws_frame_t ws_pkt;
	memset(&ws_pkt, 0, sizeof(ws_pkt));
	ws_pkt.type = ws_to_espidf_frame_type(frame->type);
	ws_pkt.payload = frame->payload;

	esp_err_t ret = httpd_ws_recv_frame(espidf_req, &ws_pkt, max_len);
	if (ret != ESP_OK) {
		if (max_len == 0) {
			log_error(TAG, "Failed to get WS frame length: %s",
			          esp_err_to_name(ret));
		} else {
			log_error(TAG, "Failed to receive WS frame: %s",
			          esp_err_to_name(ret));
		}
		return -1;
	}

	// Update frame info from ESP-IDF frame
	frame->type = espidf_to_ws_frame_type(ws_pkt.type);
	frame->len = ws_pkt.len;
	frame->final = ws_pkt.final;
	frame->fragmented = ws_pkt.fragmented;

	return 0;
}

int http_ws_send_frame(http_req *req, const ws_frame *frame) {
	if (!req || !frame || !req->platform_ctx) {
		return -1;
	}

	httpd_req_t *espidf_req = (httpd_req_t *)req->platform_ctx;

	httpd_ws_frame_t ws_pkt = {.final = frame->final,
	                           .fragmented = frame->fragmented,
	                           .type = ws_to_espidf_frame_type(frame->type),
	                           .payload = frame->payload,
	                           .len = frame->len};

	esp_err_t ret = httpd_ws_send_frame(espidf_req, &ws_pkt);
	if (ret != ESP_OK) {
		log_error(TAG, "Failed to send WS frame: %s", esp_err_to_name(ret));
		return -1;
	}

	return 0;
}

// ============================================================================
// WebSocket Client Implementation
// ============================================================================

// Internal event handler that converts ESP-IDF events to platform-independent
// events
static void espidf_ws_event_handler(void *handler_args, esp_event_base_t base,
                                    int32_t event_id, void *event_data) {
	esp_websocket_event_data_t *data = (esp_websocket_event_data_t *)event_data;

	switch (event_id) {
	case WEBSOCKET_EVENT_CONNECTED:
		ws_client_event_handler(WS_EVENT_CONNECTED, NULL);
		break;

	case WEBSOCKET_EVENT_DISCONNECTED:
		ws_client_event_handler(WS_EVENT_DISCONNECTED, NULL);
		break;

	case WEBSOCKET_EVENT_DATA:
		if (data && data->data_ptr && data->data_len > 0) {
			ws_event_data evt = {.data = (const uint8_t *)data->data_ptr,
			                     .data_len = data->data_len};
			ws_client_event_handler(WS_EVENT_DATA, &evt);
		}
		break;

	case WEBSOCKET_EVENT_ERROR:
		ws_client_event_handler(WS_EVENT_ERROR, NULL);
		break;

	default:
		break;
	}
}

ws_client_handle_t ws_client_init(const char *uri) {
	if (!uri) {
		log_error(TAG, "Invalid URI for WebSocket client");
		return NULL;
	}

	esp_websocket_client_config_t ws_cfg = {
	    .uri = uri,
	    .reconnect_timeout_ms = 5000,
	    .network_timeout_ms = 10000,
	};

	esp_websocket_client_handle_t client = esp_websocket_client_init(&ws_cfg);
	if (!client) {
		log_error(TAG, "Failed to initialize WebSocket client");
		return NULL;
	}

	// Register our internal event handler
	esp_err_t ret = esp_websocket_register_events(
	    client, WEBSOCKET_EVENT_ANY, espidf_ws_event_handler, NULL);
	if (ret != ESP_OK) {
		log_error(TAG, "Failed to register event handler: %s",
		          esp_err_to_name(ret));
		esp_websocket_client_destroy(client);
		return NULL;
	}

	return (ws_client_handle_t)client;
}

int ws_client_start(ws_client_handle_t client) {
	if (!client) {
		return -1;
	}

	esp_websocket_client_handle_t espidf_client =
	    (esp_websocket_client_handle_t)client;
	esp_err_t ret = esp_websocket_client_start(espidf_client);
	if (ret != ESP_OK) {
		log_error(TAG, "Failed to start WebSocket client: %s",
		          esp_err_to_name(ret));
		return -1;
	}

	return 0;
}

int ws_client_stop(ws_client_handle_t client) {
	if (!client) {
		return -1;
	}

	esp_websocket_client_handle_t espidf_client =
	    (esp_websocket_client_handle_t)client;
	esp_err_t ret = esp_websocket_client_stop(espidf_client);
	if (ret != ESP_OK) {
		log_error(TAG, "Failed to stop WebSocket client: %s",
		          esp_err_to_name(ret));
		return -1;
	}

	return 0;
}

int ws_client_send_binary(ws_client_handle_t client, const uint8_t *data,
                          size_t len) {
	if (!client || !data) {
		return -1;
	}

	esp_websocket_client_handle_t espidf_client =
	    (esp_websocket_client_handle_t)client;
	int sent = esp_websocket_client_send_bin(espidf_client, (const char *)data,
	                                         len, portMAX_DELAY);
	if (sent < 0) {
		log_error(TAG, "Failed to send binary data");
		return -1;
	}

	return 0;
}

int ws_client_send_text(ws_client_handle_t client, const char *data,
                        size_t len) {
	if (!client || !data) {
		return -1;
	}

	esp_websocket_client_handle_t espidf_client =
	    (esp_websocket_client_handle_t)client;
	int sent =
	    esp_websocket_client_send_text(espidf_client, data, len, portMAX_DELAY);
	if (sent < 0) {
		log_error(TAG, "Failed to send text data");
		return -1;
	}

	return 0;
}

// ============================================================================
// Platform Timer Implementation
// ============================================================================

#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

// Timer wrapper to store interval
typedef struct {
	esp_timer_handle_t timer;
	uint32_t interval_us;
} platform_timer_t;

platform_timer_handle_t platform_timer_create(void (*callback)(void *arg),
                                              void *arg, uint32_t interval_ms) {
	if (!callback) {
		return NULL;
	}

	platform_timer_t *timer_wrapper = malloc(sizeof(platform_timer_t));
	if (!timer_wrapper) {
		log_error(TAG, "Failed to allocate timer wrapper");
		return NULL;
	}

	const esp_timer_create_args_t timer_args = {
	    .callback = (esp_timer_cb_t)callback, .arg = arg, .name = "ws_timer"};

	esp_err_t ret = esp_timer_create(&timer_args, &timer_wrapper->timer);
	if (ret != ESP_OK) {
		log_error(TAG, "Failed to create timer: %s", esp_err_to_name(ret));
		free(timer_wrapper);
		return NULL;
	}

	timer_wrapper->interval_us = interval_ms * 1000;
	return (platform_timer_handle_t)timer_wrapper;
}

int platform_timer_start(platform_timer_handle_t timer) {
	if (!timer) {
		return -1;
	}

	platform_timer_t *timer_wrapper = (platform_timer_t *)timer;

	// Stop if already running
	if (esp_timer_is_active(timer_wrapper->timer)) {
		esp_timer_stop(timer_wrapper->timer);
	}

	// Start periodic timer
	esp_err_t ret = esp_timer_start_periodic(timer_wrapper->timer,
	                                         timer_wrapper->interval_us);
	if (ret != ESP_OK) {
		log_error(TAG, "Failed to start timer: %s", esp_err_to_name(ret));
		return -1;
	}

	return 0;
}

int platform_timer_stop(platform_timer_handle_t timer) {
	if (!timer) {
		return -1;
	}

	platform_timer_t *timer_wrapper = (platform_timer_t *)timer;

	if (esp_timer_is_active(timer_wrapper->timer)) {
		esp_err_t ret = esp_timer_stop(timer_wrapper->timer);
		if (ret != ESP_OK) {
			log_error(TAG, "Failed to stop timer: %s", esp_err_to_name(ret));
			return -1;
		}
	}

	return 0;
}

void platform_timer_delete(platform_timer_handle_t timer) {
	if (!timer) {
		return;
	}

	platform_timer_t *timer_wrapper = (platform_timer_t *)timer;

	if (esp_timer_is_active(timer_wrapper->timer)) {
		esp_timer_stop(timer_wrapper->timer);
	}

	esp_timer_delete(timer_wrapper->timer);
	free(timer_wrapper);
}

void platform_delay_ms(uint32_t ms) { vTaskDelay(pdMS_TO_TICKS(ms)); }

#endif // ESP_PLATFORM
