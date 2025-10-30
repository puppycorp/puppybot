#ifndef HTTP_H
#define HTTP_H

#define HTTP_METHOD_GET 1

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct http_server http_server;
typedef struct http_req http_req;

// WebSocket frame types - platform independent
typedef enum {
	WS_FRAME_TEXT = 0x01,
	WS_FRAME_BINARY = 0x02,
	WS_FRAME_CLOSE = 0x08,
	WS_FRAME_PING = 0x09,
	WS_FRAME_PONG = 0x0A
} ws_frame_type_t;

// WebSocket client event types - platform independent
typedef enum {
	WS_EVENT_CONNECTED = 0,
	WS_EVENT_DISCONNECTED = 1,
	WS_EVENT_DATA = 2,
	WS_EVENT_ERROR = 3
} ws_event_type_t;

// WebSocket frame - platform independent
typedef struct ws_frame {
	ws_frame_type_t type;
	uint8_t *payload;
	size_t len;
	bool final;
	bool fragmented;
} ws_frame;

// WebSocket client event data - platform independent
typedef struct ws_event_data {
	const uint8_t *data;
	size_t data_len;
} ws_event_data;

typedef struct http_route {
	const char *path;
	int method;
	int (*handler)(http_req *req);
	void *ctx;
} http_route;

// HTTP server functions
http_server *http_server_init(void);
void http_register_handler(http_server *server, const http_route *handler);
void http_server_start(void);

// Start HTTP/WebSocket client with server URI and heartbeat interval
// Pass NULL for server_uri to skip client initialization
void http_client_start(const char *server_uri, uint32_t heartbeat_interval_ms);

// WebSocket server handler - handles incoming WebSocket connections
// This is the main handler that should be registered with the HTTP server
int ws_httpd_handler(http_req *req);

// WebSocket client configuration
typedef struct ws_client_config {
	const char *uri;
	bool enable_heartbeat;          // Enable heartbeat ping/pong
	uint32_t heartbeat_interval_ms; // Heartbeat interval in milliseconds
	bool enable_auto_reconnect;     // Enable automatic reconnection
	uint32_t reconnect_delay_ms;    // Delay before reconnection attempt

	// Optional application callback when connected (e.g., to send device info)
	void (*on_connected_cb)(void);
} ws_client_config;

// WebSocket client initialization with configuration
// Returns 0 on success, non-zero on error
int ws_client_init_and_start(const ws_client_config *config);

// Stop and cleanup WebSocket client
void ws_client_shutdown(void);

// Check if WebSocket client is connected
bool ws_client_is_connected(void);

// Send binary data via WebSocket client
int ws_client_send(const uint8_t *data, size_t len);

// Send device information (firmware version, variant) to server
void ws_client_send_device_info(void);

// WebSocket client event handler callback
// Platform implementations should call this when client events occur
void ws_client_event_handler(ws_event_type_t event_type,
                             const ws_event_data *event_data);

// ============================================================================
// Platform-specific interface to be implemented by each platform (ESP-IDF,
// Unix, etc.)
// ============================================================================

// Platform-specific request structure - platforms should define this
struct http_req {
	int method;
	void *platform_ctx; // Platform-specific context (e.g., httpd_req_t* for
	                    // ESP-IDF)
};

// Platform-specific WebSocket functions that must be implemented
// Returns 0 on success, non-zero on error

// Receive a WebSocket frame from the server
// If max_len is 0, only fills in frame metadata (type, len) without payload
int http_ws_recv_frame(http_req *req, ws_frame *frame, size_t max_len);

// Send a WebSocket frame to the client
int http_ws_send_frame(http_req *req, const ws_frame *frame);

// WebSocket client handle (opaque, platform-specific)
typedef void *ws_client_handle_t;

// Platform implementations must provide these functions:

// Initialize WebSocket client with URI and setup event handlers
// Event handlers should call ws_client_event_handler() defined above
ws_client_handle_t ws_client_init(const char *uri);

// Start WebSocket client connection
int ws_client_start(ws_client_handle_t client);

// Stop WebSocket client connection
int ws_client_stop(ws_client_handle_t client);

// Send binary data via WebSocket client
int ws_client_send_binary(ws_client_handle_t client, const uint8_t *data,
                          size_t len);

// Send text data via WebSocket client
int ws_client_send_text(ws_client_handle_t client, const char *data,
                        size_t len);

#endif
