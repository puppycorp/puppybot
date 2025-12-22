#include "main.h"
#include "motor_runtime.h"
#include "test.h"

#include <string.h>

#define MAX_SERVO_COUNT 8
#define MAX_CALLS 32

typedef enum {
	CALL_STORAGE,
	CALL_LOG,
	CALL_WIFI,
	CALL_MDNS,
	CALL_MOTOR_INIT,
	CALL_DELAY,
	CALL_COMMAND_HANDLER,
	CALL_BLUETOOTH,
	CALL_WEBSOCKET,
} CallTag;

typedef struct {
	int storage_result;
	int wifi_result;
	int mdns_result;
	int bluetooth_result;
	int websocket_result;
	uint32_t delay_ms;
	CallTag call_log[MAX_CALLS];
	size_t call_count;
} AppStub;

static AppStub stub;

static void log_call(CallTag tag) {
	if (stub.call_count < MAX_CALLS) {
		stub.call_log[stub.call_count++] = tag;
	}
}

const char *instance_name(void) { return "StubInstance"; }

void log_info(const char *tag, const char *format, ...) {
	log_call(CALL_LOG);
	(void)tag;
	(void)format;
}

void log_warn(const char *tag, const char *format, ...) {
	(void)tag;
	(void)format;
}

void log_error(const char *tag, const char *format, ...) {
	(void)tag;
	(void)format;
}

PuppybotStatus platform_init(void) {
	log_call(CALL_STORAGE);
	if (stub.storage_result != 0) {
		return PUPPYBOT_ERR_STORAGE;
	}
	log_call(CALL_WIFI);
	if (stub.wifi_result != 0) {
		return PUPPYBOT_ERR_WIFI;
	}
	log_call(CALL_MDNS);
	if (stub.mdns_result != 0) {
		return PUPPYBOT_ERR_MDNS;
	}
	log_call(CALL_MOTOR_INIT);
	return PUPPYBOT_OK;
}

void delay_ms(uint32_t ms) {
	log_call(CALL_DELAY);
	stub.delay_ms = ms;
}

void command_handler_init(void) { log_call(CALL_COMMAND_HANDLER); }

int bluetooth_start(void) {
	log_call(CALL_BLUETOOTH);
	return stub.bluetooth_result;
}

const char *platform_get_server_uri(void) {
	return "ws://test-server/api/bot/test/ws";
}

void http_server_start(void) { log_call(CALL_WEBSOCKET); }

void http_client_start(const char *server_uri, uint32_t heartbeat_interval_ms) {
	(void)server_uri;
	(void)heartbeat_interval_ms;
}

const char *platform_get_bot_id(void) { return "test-bot"; }

int platform_store_bot_id(const char *bot_id) {
	(void)bot_id;
	return 0;
}

// Stub for motor_slots functions
void motor_slots_reset(void) {}

int motor_slots_drive_count(void) { return 0; }

motor_rt_t *motor_slots_drive(int idx) {
	(void)idx;
	return NULL;
}

int motor_slots_servo_count(void) { return 0; }

motor_rt_t *motor_slots_servo(int idx) {
	(void)idx;
	return NULL;
}

void motor_slots_register(motor_rt_t *m) {
	(void)m;
}

float motor_slots_servo_boot_angle(int idx) {
	(void)idx;
	return 90.0f;
}

static void stub_reset(void) {
	memset(&stub, 0, sizeof(stub));
	stub.storage_result = 0;
	stub.wifi_result = 0;
	stub.mdns_result = 0;
	stub.bluetooth_result = 0;
	stub.websocket_result = 0;
}

static void assert_call_order(size_t expected_count, const CallTag *expected) {
	ASSERT_EQ(stub.call_count, expected_count);
	for (size_t i = 0; i < expected_count; ++i) {
		ASSERT_EQ(stub.call_log[i], expected[i]);
	}
}

TEST(puppybot_main_runs_full_boot_sequence) {
	stub_reset();

	PuppybotStatus status = puppybot_main();
	ASSERT_EQ(status, PUPPYBOT_OK);

	const CallTag expected[] = {
	    CALL_STORAGE,         CALL_WIFI,      CALL_MDNS,
	    CALL_MOTOR_INIT,      CALL_LOG,       CALL_DELAY,
	    CALL_COMMAND_HANDLER, CALL_BLUETOOTH, CALL_WEBSOCKET};
	assert_call_order(sizeof(expected) / sizeof(expected[0]), expected);
	ASSERT_EQ(stub.delay_ms, 5000u);
}

TEST(puppybot_main_propagates_storage_failure) {
	stub_reset();
	stub.storage_result = -1;

	PuppybotStatus status = puppybot_main();
	ASSERT_EQ(status, PUPPYBOT_ERR_STORAGE);
	const CallTag expected[] = {CALL_STORAGE};
	assert_call_order(sizeof(expected) / sizeof(expected[0]), expected);
}

TEST(puppybot_main_propagates_wifi_failure) {
	stub_reset();
	stub.wifi_result = -1;

	PuppybotStatus status = puppybot_main();
	ASSERT_EQ(status, PUPPYBOT_ERR_WIFI);
	const CallTag expected[] = {CALL_STORAGE, CALL_WIFI};
	assert_call_order(sizeof(expected) / sizeof(expected[0]), expected);
}

TEST(puppybot_main_propagates_bluetooth_failure) {
	stub_reset();
	stub.bluetooth_result = -1;

	PuppybotStatus status = puppybot_main();
	ASSERT_EQ(status, PUPPYBOT_ERR_BLUETOOTH);
	const CallTag expected[] = {CALL_STORAGE,         CALL_WIFI,     CALL_MDNS,
	                            CALL_MOTOR_INIT,      CALL_LOG,      CALL_DELAY,
	                            CALL_COMMAND_HANDLER, CALL_BLUETOOTH};
	assert_call_order(sizeof(expected) / sizeof(expected[0]), expected);
}
