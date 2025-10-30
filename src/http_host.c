#include "http.h"

#include "log.h"
#include "platform.h"
#include "protocol.h"

#include <arpa/inet.h>
#include <errno.h>
#include <limits.h>
#include <netdb.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#define WS_THREAD_STACK_SIZE (64 * 1024)

struct http_server {
	const http_route *route;
};

typedef struct ws_client_impl {
	char *uri;
	char *host;
	char *path;
	int port;

	int sock;
	pthread_t thread;
	pthread_mutex_t send_lock;

	bool running;
	bool stop_requested;
	bool connected;
} ws_client_impl;

static const char *TAG = "HTTP_HOST";

#define SERVO_LOG_INTERVAL_MS 50
#define SERVO_LOG_ANGLE_DELTA 2
#define DRIVE_LOG_INTERVAL_MS 50
#define DRIVE_LOG_SPEED_DELTA 3

typedef struct {
	bool valid;
	int last_speed;
	int last_angle;
	uint32_t last_log_ms;
} command_log_state;

static command_log_state g_drive_log[256];

// -----------------------------------------------------------------------------
// Utility helpers
// -----------------------------------------------------------------------------

static void fill_random_bytes(uint8_t *buf, size_t len) {
	FILE *fp = fopen("/dev/urandom", "rb");
	if (fp) {
		size_t read_len = fread(buf, 1, len, fp);
		fclose(fp);
		if (read_len == len) {
			return;
		}
	}

	for (size_t i = 0; i < len; i++) {
		buf[i] = (uint8_t)(rand() & 0xff);
	}
}

static size_t base64_encode(const uint8_t *input, size_t len, char *output,
                            size_t output_len) {
	static const char alphabet[] =
	    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

	size_t required = ((len + 2) / 3) * 4;
	if (output_len < required + 1) {
		return 0;
	}

	size_t out_idx = 0;
	for (size_t i = 0; i < len; i += 3) {
		uint32_t chunk = (uint32_t)input[i] << 16;
		if (i + 1 < len) {
			chunk |= (uint32_t)input[i + 1] << 8;
		}
		if (i + 2 < len) {
			chunk |= (uint32_t)input[i + 2];
		}

		output[out_idx++] = alphabet[(chunk >> 18) & 0x3f];
		output[out_idx++] = alphabet[(chunk >> 12) & 0x3f];
		output[out_idx++] = (i + 1 < len) ? alphabet[(chunk >> 6) & 0x3f] : '=';
		output[out_idx++] = (i + 2 < len) ? alphabet[chunk & 0x3f] : '=';
	}

	output[out_idx] = '\0';
	return out_idx;
}

typedef struct {
	uint32_t state[5];
	uint32_t count[2];
	uint8_t buffer[64];
} sha1_ctx;

static void sha1_transform(uint32_t state[5], const uint8_t buffer[64]) {
	uint32_t a = state[0];
	uint32_t b = state[1];
	uint32_t c = state[2];
	uint32_t d = state[3];
	uint32_t e = state[4];

	uint32_t w[80];
	for (int t = 0; t < 16; t++) {
		w[t] = ((uint32_t)buffer[t * 4]) << 24 |
		       ((uint32_t)buffer[t * 4 + 1]) << 16 |
		       ((uint32_t)buffer[t * 4 + 2]) << 8 |
		       ((uint32_t)buffer[t * 4 + 3]);
	}
	for (int t = 16; t < 80; t++) {
		uint32_t tmp = w[t - 3] ^ w[t - 8] ^ w[t - 14] ^ w[t - 16];
		w[t] = (tmp << 1) | (tmp >> 31);
	}

	for (int t = 0; t < 80; t++) {
		uint32_t k, f;
		if (t < 20) {
			f = (b & c) | ((~b) & d);
			k = 0x5a827999;
		} else if (t < 40) {
			f = b ^ c ^ d;
			k = 0x6ed9eba1;
		} else if (t < 60) {
			f = (b & c) | (b & d) | (c & d);
			k = 0x8f1bbcdc;
		} else {
			f = b ^ c ^ d;
			k = 0xca62c1d6;
		}

		uint32_t tmp = ((a << 5) | (a >> 27)) + f + e + k + w[t];
		e = d;
		d = c;
		c = (b << 30) | (b >> 2);
		b = a;
		a = tmp;
	}

	state[0] += a;
	state[1] += b;
	state[2] += c;
	state[3] += d;
	state[4] += e;
}

static void sha1_init(sha1_ctx *ctx) {
	ctx->state[0] = 0x67452301;
	ctx->state[1] = 0xefcdab89;
	ctx->state[2] = 0x98badcfe;
	ctx->state[3] = 0x10325476;
	ctx->state[4] = 0xc3d2e1f0;
	ctx->count[0] = ctx->count[1] = 0;
	memset(ctx->buffer, 0, sizeof(ctx->buffer));
}

static void sha1_update(sha1_ctx *ctx, const uint8_t *data, size_t len) {
	uint32_t j = (ctx->count[0] >> 3) & 63;
	uint32_t i;

	if ((ctx->count[0] += (uint32_t)len << 3) < ((uint32_t)len << 3)) {
		ctx->count[1]++;
	}
	ctx->count[1] += (uint32_t)(len >> 29);

	if ((j + len) > 63) {
		i = 64 - j;
		memcpy(&ctx->buffer[j], data, i);
		sha1_transform(ctx->state, ctx->buffer);
		for (; i + 63 < len; i += 64) {
			sha1_transform(ctx->state, &data[i]);
		}
		j = 0;
	} else {
		i = 0;
	}
	memcpy(&ctx->buffer[j], &data[i], len - i);
}

static void sha1_final(sha1_ctx *ctx, uint8_t digest[20]) {
	uint8_t final_count[8];
	for (int i = 0; i < 8; i++) {
		final_count[i] =
		    (uint8_t)((ctx->count[(i >= 4 ? 0 : 1)] >> ((3 - (i & 3)) * 8)) &
		              255);
	}

	uint8_t c = 0200;
	sha1_update(ctx, &c, 1);
	while ((ctx->count[0] & 504) != 448) {
		c = 0;
		sha1_update(ctx, &c, 1);
	}

	sha1_update(ctx, final_count, 8);
	for (int i = 0; i < 20; i++) {
		digest[i] = (uint8_t)((ctx->state[i / 4] >> ((3 - (i & 3)) * 8)) & 255);
	}

	memset(ctx, 0, sizeof(*ctx));
	memset(final_count, 0, sizeof(final_count));
}

static bool compute_accept_key(const char *client_key, char *out,
                               size_t out_len) {
	static const char guid[] = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
	uint8_t sha_input[60];
	size_t key_len = strlen(client_key);
	if (key_len + sizeof(guid) - 1 > sizeof(sha_input)) {
		return false;
	}

	memcpy(sha_input, client_key, key_len);
	memcpy(sha_input + key_len, guid, sizeof(guid) - 1);

	uint8_t digest[20];
	sha1_ctx ctx;
	sha1_init(&ctx);
	sha1_update(&ctx, sha_input, key_len + sizeof(guid) - 1);
	sha1_final(&ctx, digest);

	return base64_encode(digest, sizeof(digest), out, out_len) > 0;
}

static bool parse_ws_uri(const char *uri, char **host_out, int *port_out,
                         char **path_out) {
	if (!uri) {
		return false;
	}

	const char *prefix = "ws://";
	const size_t prefix_len = strlen(prefix);
	if (strncmp(uri, prefix, prefix_len) != 0) {
		log_error(TAG, "Unsupported URI scheme (only ws:// is supported)");
		return false;
	}

	const char *host_start = uri + prefix_len;
	const char *path_start = strchr(host_start, '/');
	char *path = NULL;
	char *authority = NULL;

	if (path_start) {
		authority = strndup(host_start, (size_t)(path_start - host_start));
		path = strdup(path_start);
	} else {
		authority = strdup(host_start);
		path = strdup("/");
	}

	if (!authority || !path) {
		free(authority);
		free(path);
		return false;
	}

	char *host = NULL;
	int port = 80;

	if (authority[0] == '[') {
		char *end = strchr(authority, ']');
		if (!end) {
			free(authority);
			free(path);
			return false;
		}

		host = strndup(authority + 1, (size_t)(end - authority - 1));
		if (end[1] == ':' && end[2] != '\0') {
			port = atoi(end + 2);
		}
	} else {
		char *colon = strrchr(authority, ':');
		if (colon && colon[1] != '\0') {
			host = strndup(authority, (size_t)(colon - authority));
			port = atoi(colon + 1);
		} else {
			host = strdup(authority);
		}
	}

	free(authority);

	if (!host || host[0] == '\0') {
		free(host);
		free(path);
		return false;
	}

	*host_out = host;
	*port_out = port;
	*path_out = path;
	return true;
}

static int connect_socket(const char *host, int port) {
	char port_str[16];
	snprintf(port_str, sizeof(port_str), "%d", port);

	struct addrinfo hints;
	memset(&hints, 0, sizeof(hints));
	hints.ai_family = AF_UNSPEC;
	hints.ai_socktype = SOCK_STREAM;

	struct addrinfo *res = NULL;
	int err = getaddrinfo(host, port_str, &hints, &res);
	if (err != 0) {
		log_error(TAG, "getaddrinfo failed: %s", gai_strerror(err));
		return -1;
	}

	int sock = -1;
	for (struct addrinfo *ai = res; ai != NULL; ai = ai->ai_next) {
		sock = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
		if (sock < 0) {
			continue;
		}

		if (connect(sock, ai->ai_addr, ai->ai_addrlen) == 0) {
			break;
		}

		close(sock);
		sock = -1;
	}

	freeaddrinfo(res);
	return sock;
}

static int recv_exact(int sock, uint8_t *buf, size_t len) {
	size_t total = 0;
	while (total < len) {
		ssize_t read_len = recv(sock, buf + total, len - total, 0);
		if (read_len <= 0) {
			return -1;
		}
		total += (size_t)read_len;
	}
	return 0;
}

static int send_buffer(int sock, const uint8_t *buf, size_t len) {
	size_t total = 0;
	while (total < len) {
		ssize_t written = send(sock, buf + total, len - total, 0);
		if (written <= 0) {
			return -1;
		}
		total += (size_t)written;
	}
	return 0;
}

// -----------------------------------------------------------------------------
// Host HTTP server (stub)
// -----------------------------------------------------------------------------

http_server *http_server_init(void) {
	static http_server server = {0};
	log_info(TAG, "HTTP server stub initialized");
	server.route = NULL;
	return &server;
}

void http_register_handler(http_server *server, const http_route *handler) {
	if (!server || !handler) {
		log_warn(TAG, "Attempted to register null handler");
		return;
	}
	server->route = handler;
	log_info(TAG, "Registered handler for %s (stub)", handler->path);
}

int http_ws_recv_frame(http_req *req, ws_frame *frame, size_t max_len) {
	(void)req;
	(void)frame;
	(void)max_len;
	log_warn(TAG, "http_ws_recv_frame called in host stub");
	return -1;
}

int http_ws_send_frame(http_req *req, const ws_frame *frame) {
	(void)req;
	if (!frame) {
		return -1;
	}
	const size_t preview = frame->len < 16 ? frame->len : 16;
	log_info(TAG, "WS send frame type=%d len=%zu preview=%.*s", frame->type,
	         frame->len, (int)preview,
	         frame->payload ? (const char *)frame->payload : "");
	return 0;
}

// -----------------------------------------------------------------------------
// Host WebSocket client implementation
// -----------------------------------------------------------------------------

static void dispatch_event(ws_event_type_t type, const uint8_t *data,
                           size_t len) {
	if (type == WS_EVENT_DATA && data && len > 0) {
		ws_event_data event = {.data = data, .data_len = len};
		ws_client_event_handler(type, &event);
	} else {
		ws_client_event_handler(type, NULL);
	}
}

static int ws_send_frame(ws_client_impl *client, uint8_t opcode,
                         const uint8_t *data, size_t len);

static int perform_handshake(ws_client_impl *client, const char *sec_key) {
	char request[1024];
	const char *host_header = client->host;
	char host_with_port[256];
	if (client->port != 80) {
		snprintf(host_with_port, sizeof(host_with_port), "%s:%d", client->host,
		         client->port);
		host_header = host_with_port;
	}

	int written = snprintf(request, sizeof(request),
	                       "GET %s HTTP/1.1\r\n"
	                       "Host: %s\r\n"
	                       "Upgrade: websocket\r\n"
	                       "Connection: Upgrade\r\n"
	                       "Sec-WebSocket-Key: %s\r\n"
	                       "Sec-WebSocket-Version: 13\r\n"
	                       "\r\n",
	                       client->path, host_header, sec_key);
	if (written <= 0 || written >= (int)sizeof(request)) {
		return -1;
	}

	if (send_buffer(client->sock, (const uint8_t *)request, (size_t)written) !=
	    0) {
		return -1;
	}

	char response[2048];
	size_t received = 0;
	while (received + 1 < sizeof(response)) {
		ssize_t r = recv(client->sock, response + received, 1, 0);
		if (r <= 0) {
			return -1;
		}
		received += (size_t)r;
		if (received >= 4 &&
		    memcmp(response + received - 4, "\r\n\r\n", 4) == 0) {
			break;
		}
	}
	response[received] = '\0';

	if (strstr(response, " 101 ") == NULL &&
	    strstr(response, " 101\r\n") == NULL) {
		log_error(TAG, "WebSocket handshake failed: %s", response);
		return -1;
	}

	char expected_accept[64];
	if (!compute_accept_key(sec_key, expected_accept,
	                        sizeof(expected_accept))) {
		return -1;
	}

	const char *accept_header = strstr(response, "Sec-WebSocket-Accept:");
	if (!accept_header) {
		log_error(TAG, "Missing Sec-WebSocket-Accept header");
		return -1;
	}

	const char *value_start = accept_header + strlen("Sec-WebSocket-Accept:");
	while (*value_start == ' ') {
		value_start++;
	}

	char actual[64];
	size_t idx = 0;
	while (*value_start && *value_start != '\r' && idx + 1 < sizeof(actual)) {
		actual[idx++] = *value_start++;
	}
	actual[idx] = '\0';

	if (strcmp(actual, expected_accept) != 0) {
		log_error(TAG, "Sec-WebSocket-Accept mismatch");
		return -1;
	}

	return 0;
}

static bool should_log_drive_command(const CommandPacket *packet) {
	int motor_id = packet->cmd.drive_motor.motor_id;
	if (motor_id < 0 || motor_id >= 256) {
		motor_id &= 0xFF;
	}

	command_log_state *state = &g_drive_log[motor_id];
	uint32_t now_ms = platform_get_time_ms();
	bool should_log = true;

	if (packet->cmd.drive_motor.motor_type == SERVO_MOTOR) {
		int angle = packet->cmd.drive_motor.angle;
		if (state->valid) {
			if ((uint32_t)(now_ms - state->last_log_ms) <
			        SERVO_LOG_INTERVAL_MS &&
			    abs(angle - state->last_angle) < SERVO_LOG_ANGLE_DELTA) {
				should_log = false;
			}
		}
		state->last_angle = angle;
	} else {
		int speed = packet->cmd.drive_motor.speed;
		if (state->valid) {
			if ((uint32_t)(now_ms - state->last_log_ms) <
			        DRIVE_LOG_INTERVAL_MS &&
			    abs(speed - state->last_speed) < DRIVE_LOG_SPEED_DELTA) {
				should_log = false;
			}
		}
		state->last_speed = packet->cmd.drive_motor.speed;
	}

	state->valid = true;
	state->last_log_ms = now_ms;

	return should_log;
}

static void log_binary_command(const uint8_t *payload, size_t len) {
	if (!payload || len < 4) {
		return;
	}

	CommandPacket packet;
	parse_cmd((uint8_t *)payload, &packet);

	const char *cmd_name = command_type_to_string(packet.cmd_type);
	switch (packet.cmd_type) {
	case CMD_DRIVE_MOTOR:
		if (!should_log_drive_command(&packet)) {
			break;
		}
		log_info(
		    TAG,
		    "RX command %s motorId=%d type=%s speed=%d steps=%d "
		    "stepTime=%d angle=%d",
		    cmd_name, packet.cmd.drive_motor.motor_id,
		    packet.cmd.drive_motor.motor_type == SERVO_MOTOR ? "SERVO" : "DC",
		    packet.cmd.drive_motor.speed, packet.cmd.drive_motor.steps,
		    packet.cmd.drive_motor.step_time, packet.cmd.drive_motor.angle);
		break;
	case CMD_STOP_MOTOR:
		log_info(TAG, "RX command %s motorId=%d", cmd_name,
		         packet.cmd.stop_motor.motor_id);
		break;
	case CMD_APPLY_CONFIG:
		log_info(TAG, "RX command %s payloadLen=%u", cmd_name,
		         packet.cmd.apply_config.length);
		break;
	default:
		log_info(TAG, "RX command %s", cmd_name);
		break;
	}
}

static void handle_incoming_frame(ws_client_impl *client, uint8_t opcode,
                                  const uint8_t *payload, size_t len) {
	switch (opcode) {
	case 0x1: // text
		dispatch_event(WS_EVENT_DATA, payload, len);
		break;
	case 0x2: // binary
		log_binary_command(payload, len);
		dispatch_event(WS_EVENT_DATA, payload, len);
		break;
	case 0x8: // close
		log_info(TAG, "WebSocket close frame received");
		client->stop_requested = true;
		break;
	case 0x9: // ping
		log_info(TAG, "WebSocket ping received");
		pthread_mutex_lock(&client->send_lock);
		const int rc = ws_send_frame(client, 0xA, payload, len);
		pthread_mutex_unlock(&client->send_lock);
		if (rc != 0) {
			log_warn(TAG, "Failed to reply to ping");
		}
		break;
	case 0xA: // pong
		log_info(TAG, "WebSocket pong received");
		break;
	default:
		log_warn(TAG, "Unhandled opcode 0x%02x", opcode);
	}
}

static int ws_send_frame(ws_client_impl *client, uint8_t opcode,
                         const uint8_t *data, size_t len) {
	if (!client->connected) {
		return -1;
	}

	uint8_t header[14];
	size_t header_len = 0;

	header[header_len++] = 0x80 | (opcode & 0x0f);

	uint8_t mask_key[4];
	fill_random_bytes(mask_key, sizeof(mask_key));

	if (len <= 125) {
		header[header_len++] = 0x80 | (uint8_t)len;
	} else if (len <= 0xffff) {
		header[header_len++] = 0x80 | 126;
		header[header_len++] = (uint8_t)((len >> 8) & 0xff);
		header[header_len++] = (uint8_t)(len & 0xff);
	} else {
		header[header_len++] = 0x80 | 127;
		for (int i = 7; i >= 0; i--) {
			header[header_len++] = (uint8_t)((len >> (i * 8)) & 0xff);
		}
	}

	memcpy(&header[header_len], mask_key, sizeof(mask_key));
	header_len += sizeof(mask_key);

	uint8_t *masked = NULL;
	if (len > 0) {
		masked = malloc(len);
		if (!masked) {
			return -1;
		}
		for (size_t i = 0; i < len; i++) {
			masked[i] = data[i] ^ mask_key[i % 4];
		}
	}

	int rc = send_buffer(client->sock, header, header_len);
	if (rc == 0 && len > 0) {
		rc = send_buffer(client->sock, masked, len);
	}

	free(masked);
	return rc;
}

static void *ws_client_thread(void *arg) {
	ws_client_impl *client = (ws_client_impl *)arg;

	uint8_t key_bytes[16];
	char key_base64[32];
	fill_random_bytes(key_bytes, sizeof(key_bytes));
	base64_encode(key_bytes, sizeof(key_bytes), key_base64, sizeof(key_base64));

	client->sock = connect_socket(client->host, client->port);
	if (client->sock < 0) {
		log_error(TAG, "Failed to connect to %s:%d", client->host,
		          client->port);
		dispatch_event(WS_EVENT_ERROR, NULL, 0);
		client->running = false;
		return NULL;
	}

	if (perform_handshake(client, key_base64) != 0) {
		log_error(TAG, "WebSocket handshake failed");
		close(client->sock);
		client->sock = -1;
		dispatch_event(WS_EVENT_ERROR, NULL, 0);
		client->running = false;
		return NULL;
	}

	client->connected = true;
	log_info(TAG, "WebSocket client connected");
	dispatch_event(WS_EVENT_CONNECTED, NULL, 0);

	uint8_t header[2];
	while (!client->stop_requested) {
		if (recv_exact(client->sock, header, sizeof(header)) != 0) {
			break;
		}

		uint8_t opcode = header[0] & 0x0f;
		uint8_t mask = header[1] & 0x80;
		uint64_t payload_len = header[1] & 0x7f;

		if (payload_len == 126) {
			uint8_t ext[2];
			if (recv_exact(client->sock, ext, sizeof(ext)) != 0) {
				break;
			}
			payload_len = ((uint64_t)ext[0] << 8) | (uint64_t)ext[1];
		} else if (payload_len == 127) {
			uint8_t ext[8];
			if (recv_exact(client->sock, ext, sizeof(ext)) != 0) {
				break;
			}
			payload_len = 0;
			for (int i = 0; i < 8; i++) {
				payload_len = (payload_len << 8) | ext[i];
			}
		}

		uint8_t masking_key[4];
		if (mask) {
			if (recv_exact(client->sock, masking_key, sizeof(masking_key)) !=
			    0) {
				break;
			}
		}

		uint8_t *payload = NULL;
		if (payload_len > 0) {
			if (payload_len > SIZE_MAX) {
				break;
			}
			payload = malloc((size_t)payload_len);
			if (!payload) {
				break;
			}
			if (recv_exact(client->sock, payload, (size_t)payload_len) != 0) {
				free(payload);
				break;
			}

			if (mask) {
				for (size_t i = 0; i < (size_t)payload_len; i++) {
					payload[i] ^= masking_key[i % 4];
				}
			}
		}

		handle_incoming_frame(client, opcode, payload, (size_t)payload_len);
		free(payload);
	}

	if (client->connected) {
		client->connected = false;
		dispatch_event(WS_EVENT_DISCONNECTED, NULL, 0);
	}

	if (client->sock >= 0) {
		close(client->sock);
		client->sock = -1;
	}

	client->running = false;
	return NULL;
}

// -----------------------------------------------------------------------------
// Exported interface
// -----------------------------------------------------------------------------

ws_client_handle_t ws_client_init(const char *uri) {
	if (!uri) {
		log_error(TAG, "Invalid URI for WebSocket client");
		return NULL;
	}

	ws_client_impl *client = calloc(1, sizeof(*client));
	if (!client) {
		log_error(TAG, "Failed to allocate WebSocket client");
		return NULL;
	}

	if (!parse_ws_uri(uri, &client->host, &client->port, &client->path)) {
		log_error(TAG, "Failed to parse WebSocket URI: %s", uri);
		free(client);
		return NULL;
	}

	client->uri = strdup(uri);
	client->sock = -1;
	pthread_mutex_init(&client->send_lock, NULL);

	log_info(TAG, "WebSocket client initialized for %s", uri);
	return (ws_client_handle_t)client;
}

int ws_client_start(ws_client_handle_t handle) {
	ws_client_impl *client = (ws_client_impl *)handle;
	if (!client) {
		return -1;
	}

	if (client->running) {
		return 0;
	}

	client->stop_requested = false;
	client->running = true;
	int rc = pthread_create(&client->thread, NULL, ws_client_thread, client);
	if (rc != 0) {
		log_error(TAG, "Failed to start WebSocket thread: %s", strerror(rc));
		client->running = false;
		return -1;
	}

	log_info(TAG, "Connecting WebSocket client to %s", client->uri);
	return 0;
}

int ws_client_stop(ws_client_handle_t handle) {
	ws_client_impl *client = (ws_client_impl *)handle;
	if (!client) {
		return -1;
	}

	if (!client->running) {
		return 0;
	}

	client->stop_requested = true;
	if (client->sock >= 0) {
		shutdown(client->sock, SHUT_RDWR);
	}

	pthread_join(client->thread, NULL);

	if (client->sock >= 0) {
		close(client->sock);
		client->sock = -1;
	}

	client->running = false;
	client->connected = false;

	log_info(TAG, "Stopping WebSocket client for %s", client->uri);
	return 0;
}

int ws_client_send_binary(ws_client_handle_t handle, const uint8_t *data,
                          size_t len) {
	ws_client_impl *client = (ws_client_impl *)handle;
	if (!client || !data) {
		return -1;
	}

	pthread_mutex_lock(&client->send_lock);
	int rc = ws_send_frame(client, 0x2, data, len);
	pthread_mutex_unlock(&client->send_lock);

	if (rc == 0) {
		const size_t preview = len < 16 ? len : 16;
		log_info(TAG, "WS send binary (%zu bytes) preview=%zu", len, preview);
	}
	return rc;
}

int ws_client_send_text(ws_client_handle_t handle, const char *data,
                        size_t len) {
	ws_client_impl *client = (ws_client_impl *)handle;
	if (!client || !data) {
		return -1;
	}

	pthread_mutex_lock(&client->send_lock);
	int rc = ws_send_frame(client, 0x1, (const uint8_t *)data, len);
	pthread_mutex_unlock(&client->send_lock);

	if (rc == 0) {
		const size_t preview = len < 32 ? len : 32;
		log_info(TAG, "WS send text (%zu bytes): %.*s", len, (int)preview,
		         data);
	}
	return rc;
}
