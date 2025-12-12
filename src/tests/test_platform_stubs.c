#include "http.h"
#include "platform.h"
#include "timer.h"

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct {
	void (*callback)(void *);
	void *arg;
} test_timer_t;

static test_timer_t *to_timer(timer_t handle) { return (test_timer_t *)handle; }

platform_timer_handle_t platform_timer_create(void (*callback)(void *arg),
                                              void *arg, uint32_t interval_ms) {
	(void)interval_ms;
	if (!callback) {
		return NULL;
	}
	test_timer_t *timer = (test_timer_t *)calloc(1, sizeof(*timer));
	if (!timer) {
		return NULL;
	}
	timer->callback = callback;
	timer->arg = arg;
	return (platform_timer_handle_t)timer;
}

int platform_timer_start(platform_timer_handle_t timer) {
	(void)timer;
	return 0;
}

int platform_timer_stop(platform_timer_handle_t timer) {
	(void)timer;
	return 0;
}

void platform_timer_delete(platform_timer_handle_t timer) { free(timer); }

void platform_delay_ms(uint32_t ms) { (void)ms; }

uint32_t platform_get_time_ms(void) { return 0; }

const char *platform_get_firmware_version(void) { return "tester"; }

timer_t timer_create(void (*callback)(void *arg), void *arg, const char *name) {
	(void)name;
	if (!callback) {
		return NULL;
	}
	test_timer_t *timer = (test_timer_t *)calloc(1, sizeof(*timer));
	if (timer) {
		timer->callback = callback;
		timer->arg = arg;
	}
	return (timer_t)timer;
}

int timer_start_once(timer_t handle, uint64_t timeout_us) {
	(void)timeout_us;
	test_timer_t *timer = to_timer(handle);
	return timer ? 0 : -1;
}

int timer_stop(timer_t handle) {
	test_timer_t *timer = to_timer(handle);
	return timer ? 0 : -1;
}

void timer_delete(timer_t handle) { free(to_timer(handle)); }

ws_client_handle_t ws_client_init(const char *uri) {
	return (ws_client_handle_t)uri;
}

int ws_client_start(ws_client_handle_t client) {
	(void)client;
	return 0;
}

int ws_client_stop(ws_client_handle_t client) {
	(void)client;
	return 0;
}

int ws_client_send_binary(ws_client_handle_t client, const uint8_t *data,
                          size_t len) {
	(void)client;
	(void)data;
	(void)len;
	return 0;
}

int ws_client_send_text(ws_client_handle_t client, const char *data,
                        size_t len) {
	(void)client;
	(void)data;
	(void)len;
	return 0;
}

int http_ws_recv_frame(http_req *req, ws_frame *frame, size_t max_len) {
	(void)req;
	if (frame && max_len > 0) {
		frame->len = 0;
		frame->type = WS_FRAME_BINARY;
	}
	return 0;
}

int http_ws_send_frame(http_req *req, const ws_frame *frame) {
	(void)req;
	(void)frame;
	return 0;
}

http_server *http_server_init(void) { return NULL; }

void http_register_handler(http_server *server, const http_route *handler) {
	(void)server;
	(void)handler;
}
