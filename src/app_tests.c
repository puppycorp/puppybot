#include "puppy_app.h"
#include "test.h"

#include <string.h>

#define MAX_SERVO_COUNT 8
#define MAX_CALLS 32

typedef enum {
	CALL_STORAGE,
	CALL_LOG,
	CALL_WIFI,
	CALL_MDNS,
	CALL_GPIO,
	CALL_PWM,
	CALL_SERVO,
	CALL_DELAY,
	CALL_COMMAND_HANDLER,
	CALL_BLUETOOTH,
	CALL_WEBSOCKET,
} CallTag;

typedef struct {
	PuppyHardwareOps ops;
	int storage_result;
	int wifi_result;
	int mdns_result;
	int bluetooth_result;
	int websocket_result;
	uint32_t servo_count;
	uint32_t servo_boot_angles[MAX_SERVO_COUNT];
	uint32_t servo_set_ids[MAX_SERVO_COUNT];
	uint32_t servo_set_angles[MAX_SERVO_COUNT];
	uint32_t servo_set_count;
	uint32_t delay_ms;
	const char *logged_instance;
	CallTag call_log[MAX_CALLS];
	size_t call_count;
} AppStub;

static AppStub stub;

static void log_call(CallTag tag) {
	if (stub.call_count < MAX_CALLS) {
		stub.call_log[stub.call_count++] = tag;
	}
}

static int stub_storage_init(void) {
	log_call(CALL_STORAGE);
	return stub.storage_result;
}

static const char *stub_instance_name(void) { return "StubInstance"; }

static void stub_log_boot(const char *instance_name) {
	log_call(CALL_LOG);
	stub.logged_instance = instance_name;
}

static int stub_wifi_init(void) {
	log_call(CALL_WIFI);
	return stub.wifi_result;
}

static int stub_mdns_init(void) {
	log_call(CALL_MDNS);
	return stub.mdns_result;
}

static void stub_motor_gpio_init(void) { log_call(CALL_GPIO); }

static void stub_motor_pwm_init(void) { log_call(CALL_PWM); }

static uint32_t stub_servo_count(void) { return stub.servo_count; }

static uint32_t stub_servo_boot_angle(uint32_t servo_id) {
	if (servo_id >= MAX_SERVO_COUNT) {
		return 90;
	}
	return stub.servo_boot_angles[servo_id];
}

static void stub_servo_set_angle(uint32_t servo_id, uint32_t angle) {
	log_call(CALL_SERVO);
	if (stub.servo_set_count < MAX_SERVO_COUNT) {
		stub.servo_set_ids[stub.servo_set_count] = servo_id;
		stub.servo_set_angles[stub.servo_set_count] = angle;
	}
	stub.servo_set_count++;
}

static void stub_delay_ms(uint32_t ms) {
	log_call(CALL_DELAY);
	stub.delay_ms = ms;
}

static void stub_command_handler_init(void) { log_call(CALL_COMMAND_HANDLER); }

static int stub_bluetooth_start(void) {
	log_call(CALL_BLUETOOTH);
	return stub.bluetooth_result;
}

static int stub_websocket_start(void) {
	log_call(CALL_WEBSOCKET);
	return stub.websocket_result;
}

static void stub_reset(void) {
	memset(&stub, 0, sizeof(stub));
	stub.storage_result = 0;
	stub.wifi_result = 0;
	stub.mdns_result = 0;
	stub.bluetooth_result = 0;
	stub.websocket_result = 0;
	stub.servo_count = 2;
	stub.servo_boot_angles[0] = 10;
	stub.servo_boot_angles[1] = 20;
	stub.ops.storage_init = stub_storage_init;
	stub.ops.instance_name = stub_instance_name;
	stub.ops.log_boot = stub_log_boot;
	stub.ops.wifi_init = stub_wifi_init;
	stub.ops.mdns_init = stub_mdns_init;
	stub.ops.motor_gpio_init = stub_motor_gpio_init;
	stub.ops.motor_pwm_init = stub_motor_pwm_init;
	stub.ops.servo_count = stub_servo_count;
	stub.ops.servo_boot_angle = stub_servo_boot_angle;
	stub.ops.servo_set_angle = stub_servo_set_angle;
	stub.ops.delay_ms = stub_delay_ms;
	stub.ops.command_handler_init = stub_command_handler_init;
	stub.ops.bluetooth_start = stub_bluetooth_start;
	stub.ops.websocket_start = stub_websocket_start;
}

static void assert_call_order(size_t expected_count, const CallTag *expected) {
	ASSERT_EQ(stub.call_count, expected_count);
	for (size_t i = 0; i < expected_count; ++i) {
		ASSERT_EQ(stub.call_log[i], expected[i]);
	}
}

TEST(puppy_app_main_runs_full_boot_sequence) {
	stub_reset();

	PuppyAppStatus status = puppy_app_main(&stub.ops);
	ASSERT_EQ(status, PUPPY_APP_OK);

	const CallTag expected[] = {CALL_STORAGE,   CALL_LOG,
	                            CALL_WIFI,      CALL_MDNS,
	                            CALL_GPIO,      CALL_PWM,
	                            CALL_SERVO,     CALL_SERVO,
	                            CALL_DELAY,     CALL_COMMAND_HANDLER,
	                            CALL_BLUETOOTH, CALL_WEBSOCKET};
	assert_call_order(sizeof(expected) / sizeof(expected[0]), expected);
	ASSERT_EQ(stub.servo_set_count, stub.servo_count);
	ASSERT_EQ(stub.servo_set_ids[0], 0u);
	ASSERT_EQ(stub.servo_set_angles[0], stub.servo_boot_angles[0]);
	ASSERT_EQ(stub.servo_set_ids[1], 1u);
	ASSERT_EQ(stub.servo_set_angles[1], stub.servo_boot_angles[1]);
	ASSERT_EQ(stub.delay_ms, 5000u);
	ASSERT(stub.logged_instance);
	ASSERT_EQ(strcmp(stub.logged_instance, "StubInstance"), 0);
}

TEST(puppy_app_main_propagates_storage_failure) {
	stub_reset();
	stub.storage_result = -1;

	PuppyAppStatus status = puppy_app_main(&stub.ops);
	ASSERT_EQ(status, PUPPY_APP_ERR_STORAGE);
	const CallTag expected[] = {CALL_STORAGE};
	assert_call_order(sizeof(expected) / sizeof(expected[0]), expected);
}

TEST(puppy_app_main_propagates_wifi_failure) {
	stub_reset();
	stub.wifi_result = -1;

	PuppyAppStatus status = puppy_app_main(&stub.ops);
	ASSERT_EQ(status, PUPPY_APP_ERR_WIFI);
	const CallTag expected[] = {CALL_STORAGE, CALL_LOG, CALL_WIFI};
	assert_call_order(sizeof(expected) / sizeof(expected[0]), expected);
}

TEST(puppy_app_main_propagates_bluetooth_failure) {
	stub_reset();
	stub.bluetooth_result = -1;

	PuppyAppStatus status = puppy_app_main(&stub.ops);
	ASSERT_EQ(status, PUPPY_APP_ERR_BLUETOOTH);
	const CallTag expected[] = {
	    CALL_STORAGE,  CALL_LOG,   CALL_WIFI,  CALL_MDNS,  CALL_GPIO,
	    CALL_PWM,      CALL_SERVO, CALL_SERVO, CALL_DELAY, CALL_COMMAND_HANDLER,
	    CALL_BLUETOOTH};
	assert_call_order(sizeof(expected) / sizeof(expected[0]), expected);
}

TEST(puppy_app_main_allows_missing_optional_hooks) {
	stub_reset();
	stub.ops.storage_init = NULL;
	stub.ops.log_boot = NULL;
	stub.ops.wifi_init = NULL;
	stub.ops.mdns_init = NULL;
	stub.ops.motor_gpio_init = NULL;
	stub.ops.motor_pwm_init = NULL;
	stub.ops.servo_set_angle = NULL;
	stub.ops.delay_ms = NULL;
	stub.ops.command_handler_init = NULL;
	stub.ops.bluetooth_start = NULL;
	stub.ops.websocket_start = NULL;

	PuppyAppStatus status = puppy_app_main(&stub.ops);
	ASSERT_EQ(status, PUPPY_APP_OK);
	ASSERT_EQ(stub.call_count, 0u);
}
