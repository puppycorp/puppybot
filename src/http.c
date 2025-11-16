
#include "http.h"
#include "command_handler.h"
#include "log.h"
#include "platform.h"
#include "protocol.h"

#include <stdlib.h>
#include <string.h>

static const char *TAG = "http";

// External variant configuration
extern const char *instance_name(void);

// Global WebSocket client state
static ws_client_handle_t ws_client = NULL;
static ws_client_config ws_config = {0};
static platform_timer_handle_t heartbeat_timer = NULL;
static bool client_connected = false;

// Heartbeat timer callback
static void heartbeat_timer_callback(void *arg) {
	if (client_connected && ws_client) {
		log_info(TAG, "Sending heartbeat ping");
		int ret = ws_client_send_text(ws_client, "ping", 4);
		if (ret != 0) {
			log_error(TAG, "Failed to send heartbeat ping");
		}
	}
}

// Reconnection function
static void ws_client_reconnect(void) {
	if (ws_client && !client_connected && ws_config.enable_auto_reconnect) {
		log_info(TAG, "Attempting WebSocket reconnection...");
		ws_client_stop(ws_client);
		platform_delay_ms(ws_config.reconnect_delay_ms);
		ws_client_start(ws_client);
	}
}

// Helper function to process binary frames for WebSocket client
static void ws_client_process_binary_frame(const uint8_t *payload, size_t len) {
	if (len < 4) {
		log_warn(TAG, "Ignoring short binary frame len=%zu", len);
		return;
	}

	log_info(TAG, "Processing client binary frame len=%zu", len);

	CommandPacket cmd_packet;
	parse_cmd((uint8_t *)payload, &cmd_packet);

#ifdef ESP_PLATFORM
	const char *cmd_name = command_type_to_string(cmd_packet.cmd_type);
	switch (cmd_packet.cmd_type) {
	case CMD_DRIVE_MOTOR:
		log_info(TAG,
		         "Command %s motorId=%d type=%s speed=%d steps=%d stepTime=%d "
		         "angle=%d",
		         cmd_name, cmd_packet.cmd.drive_motor.motor_id,
		         cmd_packet.cmd.drive_motor.motor_type == SERVO_MOTOR ? "SERVO"
		                                                              : "DC",
		         cmd_packet.cmd.drive_motor.speed,
		         cmd_packet.cmd.drive_motor.steps,
		         cmd_packet.cmd.drive_motor.step_time,
		         cmd_packet.cmd.drive_motor.angle);
		break;
	case CMD_STOP_MOTOR:
		log_info(TAG, "Command %s motorId=%d", cmd_name,
		         cmd_packet.cmd.stop_motor.motor_id);
		break;
	case CMD_APPLY_CONFIG:
		log_info(TAG, "Command %s payloadLen=%u", cmd_name,
		         cmd_packet.cmd.apply_config.length);
		break;
	default:
		log_info(TAG, "Command %s", cmd_name);
		break;
	}
#endif

	command_handler_handle(&cmd_packet);

	// Send PONG response for PING commands
	if (cmd_packet.cmd_type == CMD_PING) {
		const uint8_t pong_payload[] = {1, 0, MSG_TO_SRV_PONG};
		int ret = ws_client_send_binary(ws_client, pong_payload,
		                                sizeof(pong_payload));
		if (ret != 0) {
			log_error(TAG, "Failed to send PONG to server");
		}
	}
}

int ws_httpd_handler(http_req *req) {
	// Handle WebSocket handshake (initial GET request)
	if (req->method == HTTP_METHOD_GET) {
		log_info(TAG, "WebSocket server handshake completed");
		return 0;
	}

	// Use static buffer to avoid ESP-IDF bug with two-step receive pattern
	// that causes "WS frame is not properly masked" errors
	// See: https://github.com/espressif/esp-idf/issues/10874
	//      https://github.com/espressif/esp-idf/issues/15235
	#define MAX_WS_FRAME_SIZE 2048
	static uint8_t ws_buffer[MAX_WS_FRAME_SIZE];

	ws_frame frame;
	memset(&frame, 0, sizeof(frame));
	frame.type = WS_FRAME_BINARY;
	frame.payload = ws_buffer;

	// Single call to receive frame - avoids masking validation bugs
	int ret = http_ws_recv_frame(req, &frame, MAX_WS_FRAME_SIZE);
	if (ret != 0) {
		log_error(TAG, "Failed to receive WS frame");
		return ret;
	}

	// Check for oversized frames
	if (frame.len > MAX_WS_FRAME_SIZE) {
		log_error(TAG, "WS frame too large: %zu > %d", frame.len,
		          MAX_WS_FRAME_SIZE);
		return -1;
	}

	// Null-terminate text frames for safety
	if (frame.payload && frame.type == WS_FRAME_TEXT) {
		frame.payload[frame.len] = '\0';
	}

	// Process frame based on type
	switch (frame.type) {
	case WS_FRAME_BINARY:
		if (frame.len < 4) {
			log_warn(TAG, "Ignoring short binary frame len=%zu", frame.len);
			break;
		}
		log_info(TAG, "Processing binary frame len=%zu", frame.len);

		CommandPacket cmd_packet;
		parse_cmd(frame.payload, &cmd_packet);
		command_handler_handle(&cmd_packet);

		// Send PONG response for PING commands
		if (cmd_packet.cmd_type == CMD_PING) {
			const uint8_t pong_payload[] = {1, 0, MSG_TO_SRV_PONG};
			ws_frame pong_frame = {
			    .final = true,
			    .fragmented = false,
			    .type = WS_FRAME_BINARY,
			    .payload = (uint8_t *)pong_payload,
			    .len = sizeof(pong_payload),
			};
			ret = http_ws_send_frame(req, &pong_frame);
			if (ret != 0) {
				log_error(TAG, "Failed to send protocol pong");
			}
		}
		break;

	case WS_FRAME_TEXT:
		log_info(TAG, "WS text frame: %s",
		         frame.payload ? (char *)frame.payload : "<empty>");
		break;

	case WS_FRAME_PING: {
		log_info(TAG, "WS ping frame received, replying pong");
		ws_frame pong_frame = frame;
		pong_frame.type = WS_FRAME_PONG;
		ret = http_ws_send_frame(req, &pong_frame);
		if (ret != 0) {
			log_error(TAG, "Failed to send WS pong");
		}
		break;
	}

	case WS_FRAME_PONG:
		log_info(TAG, "WS pong frame received");
		break;

	case WS_FRAME_CLOSE: {
		log_info(TAG, "WS close frame received, acknowledging");
		ws_frame close_frame = {
		    .final = true,
		    .fragmented = false,
		    .type = WS_FRAME_CLOSE,
		    .payload = NULL,
		    .len = 0,
		};
		ret = http_ws_send_frame(req, &close_frame);
		if (ret != 0) {
			log_error(TAG, "Failed to acknowledge close frame");
		}
		break;
	}

	default:
		log_warn(TAG, "Unhandled WS frame type %d", frame.type);
		break;
	}

	// No need to free - using static buffer
	return ret;
}

static const http_route ws_handler = {.path = "/ws",
                                      .method = HTTP_METHOD_GET,
                                      .handler = ws_httpd_handler,
                                      .ctx = NULL};

// WebSocket client event handler
// This should be called by the platform layer when client events occur
void ws_client_event_handler(ws_event_type_t event_type,
                             const ws_event_data *event_data) {
	switch (event_type) {
	case WS_EVENT_CONNECTED:
		log_info(TAG, "WebSocket client connected");
		client_connected = true;

		// Call application callback if registered
		if (ws_config.on_connected_cb) {
			ws_config.on_connected_cb();
		}

		// Start heartbeat timer if enabled
		if (ws_config.enable_heartbeat && heartbeat_timer) {
			platform_timer_start(heartbeat_timer);
		}
		break;

	case WS_EVENT_DISCONNECTED:
		log_info(TAG, "WebSocket client disconnected");
		client_connected = false;

		// Stop heartbeat timer
		if (heartbeat_timer) {
			platform_timer_stop(heartbeat_timer);
		}

		// Attempt reconnection if enabled
		if (ws_config.enable_auto_reconnect) {
			platform_delay_ms(ws_config.reconnect_delay_ms);
			ws_client_reconnect();
		}
		break;

	case WS_EVENT_DATA:
		if (event_data && event_data->data && event_data->data_len > 0) {
			log_info(TAG, "WebSocket client received %zu bytes",
			         event_data->data_len);

			// Handle application-level heartbeat pong responses
			if (event_data->data_len == 4 &&
			    memcmp(event_data->data, "pong", 4) == 0) {
				log_info(TAG, "Received heartbeat pong");
				return;
			}

			// Handle application-level ping (ignore)
			if (event_data->data_len == 4 &&
			    memcmp(event_data->data, "ping", 4) == 0) {
				log_info(TAG, "Received ping, ignoring");
				return;
			}

			// Process binary protocol data
			ws_client_process_binary_frame(event_data->data,
			                               event_data->data_len);
		}
		break;

	case WS_EVENT_ERROR:
		log_error(TAG, "WebSocket client error");
		client_connected = false;

		// Stop heartbeat timer
		if (heartbeat_timer) {
			platform_timer_stop(heartbeat_timer);
		}

		// Attempt reconnection if enabled
		if (ws_config.enable_auto_reconnect) {
			platform_delay_ms(ws_config.reconnect_delay_ms *
			                  2); // Longer delay on error
			ws_client_reconnect();
		}
		break;

	default:
		log_warn(TAG, "Unknown WebSocket event type: %d", event_type);
		break;
	}
}

int ws_client_init_and_start(const ws_client_config *config) {
	if (!config || !config->uri) {
		log_warn(TAG, "Invalid WebSocket client configuration");
		return -1;
	}

	log_info(TAG, "Initializing WebSocket client to %s", config->uri);

	// Store configuration
	ws_config = *config;

	// Create heartbeat timer if enabled
	if (config->enable_heartbeat) {
		heartbeat_timer = platform_timer_create(heartbeat_timer_callback, NULL,
		                                        config->heartbeat_interval_ms);
		if (!heartbeat_timer) {
			log_error(TAG, "Failed to create heartbeat timer");
			// Continue anyway, not critical
		}
	}

	// Initialize WebSocket client
	ws_client = ws_client_init(config->uri);
	if (ws_client == NULL) {
		log_error(TAG, "Failed to initialize WebSocket client");
		if (heartbeat_timer) {
			platform_timer_delete(heartbeat_timer);
			heartbeat_timer = NULL;
		}
		return -1;
	}

	// Start WebSocket client
	int ret = ws_client_start(ws_client);
	if (ret != 0) {
		log_error(TAG, "Failed to start WebSocket client");
		ws_client_stop(ws_client);
		if (heartbeat_timer) {
			platform_timer_delete(heartbeat_timer);
			heartbeat_timer = NULL;
		}
		return ret;
	}

	log_info(TAG, "WebSocket client started successfully");
	return 0;
}

void ws_client_shutdown(void) {
	if (ws_client) {
		ws_client_stop(ws_client);
		ws_client = NULL;
	}

	if (heartbeat_timer) {
		platform_timer_stop(heartbeat_timer);
		platform_timer_delete(heartbeat_timer);
		heartbeat_timer = NULL;
	}

	client_connected = false;
	memset(&ws_config, 0, sizeof(ws_config));
}

bool ws_client_is_connected(void) { return client_connected; }

int ws_client_send(const uint8_t *data, size_t len) {
	if (!ws_client || !client_connected) {
		log_error(TAG, "WebSocket client not connected");
		return -1;
	}

	return ws_client_send_binary(ws_client, data, len);
}

// Send device information (firmware version, variant) to server
void ws_client_send_device_info(void) {
	if (!client_connected) {
		log_warn(TAG, "Cannot send device info: not connected");
		return;
	}

	const char *fw_version = platform_get_firmware_version();
	const char *variant = instance_name();

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
		log_error(TAG, "Failed to allocate buffer for MyInfo message");
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

	int ret = ws_client_send(payload, offset);
	if (ret != 0) {
		log_error(TAG, "Failed to send MyInfo message");
	} else {
		log_info(TAG, "Sent MyInfo (fw=%.*s, variant=%.*s)", (int)version_len,
		         fw_version, (int)variant_len, variant);
	}

	free(payload);
}

void http_server_start(void) {
	http_server *server = http_server_init();
	if (!server) {
		return;
	}

	http_register_handler(server, &ws_handler);
}

void http_client_start(const char *server_uri, uint32_t heartbeat_interval_ms) {
	if (!server_uri) {
		log_info(TAG, "No server URI provided, skipping WebSocket client");
		return;
	}

	// Configure WebSocket client with heartbeat and auto-reconnect
	ws_client_config config = {.uri = server_uri,
	                           .enable_heartbeat = true,
	                           .heartbeat_interval_ms = heartbeat_interval_ms,
	                           .enable_auto_reconnect = true,
	                           .reconnect_delay_ms = 1000,
	                           .on_connected_cb = ws_client_send_device_info};

	// Initialize and start WebSocket client
	ws_client_init_and_start(&config);
}
