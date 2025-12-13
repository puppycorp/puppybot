#include "test.h"

#include <string.h>

#include "motor_runtime.h"

typedef struct {
	uint32_t now_value;
	int init_calls;
	int ensure_calls;
	int bind_calls;
	int pulse_calls;
	int duty_calls;
	int hbridge_calls;
	uint16_t last_freq;
	uint16_t last_pulse_us;
	float last_duty_ratio;
	bool last_forward;
	bool last_brake;
} mock_hw_t;

static mock_hw_t *g_active_mock = NULL;

// Stub implementations of motor_hw functions for testing
int motor_hw_init(void) {
	if (g_active_mock)
		g_active_mock->init_calls++;
	return 0;
}

void motor_hw_ensure_pwm(uint8_t channel, uint16_t freq_hz) {
	(void)channel;
	if (!g_active_mock)
		return;
	g_active_mock->ensure_calls++;
	g_active_mock->last_freq = freq_hz;
}

void motor_hw_bind_pwm_pin(uint8_t channel, int gpio) {
	(void)channel;
	(void)gpio;
	if (!g_active_mock)
		return;
	g_active_mock->bind_calls++;
}

void motor_hw_set_pwm_pulse_us(uint8_t channel, uint16_t freq_hz,
                               uint16_t pulse_us) {
	(void)channel;
	if (!g_active_mock)
		return;
	g_active_mock->pulse_calls++;
	g_active_mock->last_freq = freq_hz;
	g_active_mock->last_pulse_us = pulse_us;
}

void motor_hw_set_pwm_duty(uint8_t channel, float duty_ratio) {
	(void)channel;
	if (!g_active_mock)
		return;
	g_active_mock->duty_calls++;
	g_active_mock->last_duty_ratio = duty_ratio;
}

void motor_hw_configure_hbridge(int in1, int in2, bool forward, bool brake) {
	(void)in1;
	(void)in2;
	if (!g_active_mock)
		return;
	g_active_mock->hbridge_calls++;
	g_active_mock->last_forward = forward;
	g_active_mock->last_brake = brake;
}

int motor_hw_configure_smartbus(uint8_t uart_port, int tx_pin, int rx_pin,
                                uint32_t baud_rate) {
	(void)uart_port;
	(void)tx_pin;
	(void)rx_pin;
	(void)baud_rate;
	return 0;
}

void motor_hw_smartbus_move(uint8_t uart_port, uint8_t servo_id,
                            uint16_t angle_x10, uint16_t duration_ms) {
	(void)uart_port;
	(void)servo_id;
	(void)angle_x10;
	(void)duration_ms;
}

void motor_hw_smartbus_set_mode(uint8_t uart_port, uint8_t servo_id,
                                uint8_t mode) {
	(void)uart_port;
	(void)servo_id;
	(void)mode;
}

void motor_hw_smartbus_set_wheel_speed(uint8_t uart_port, uint8_t servo_id,
                                       int16_t speed_raw, uint8_t acc) {
	(void)uart_port;
	(void)servo_id;
	(void)speed_raw;
	(void)acc;
}

void motor_hw_smartbus_write_u8(uint8_t uart_port, uint8_t servo_id,
                                uint8_t addr, uint8_t value) {
	(void)uart_port;
	(void)servo_id;
	(void)addr;
	(void)value;
}

int motor_hw_smartbus_read_position(uint8_t uart_port, uint8_t servo_id,
                                    uint16_t *pos_raw_out) {
	(void)uart_port;
	(void)servo_id;
	(void)pos_raw_out;
	return -2;
}

int motor_hw_smartbus_ping(uint8_t uart_port, uint8_t servo_id,
                           int timeout_ms) {
	(void)uart_port;
	(void)servo_id;
	(void)timeout_ms;
	return -2;
}

uint32_t now_ms(void) {
	if (!g_active_mock)
		return 0;
	return g_active_mock->now_value;
}

static void mock_hw_setup(mock_hw_t *mock) {
	memset(mock, 0, sizeof(*mock));
	g_active_mock = mock;
}

static void mock_hw_teardown(void) { g_active_mock = NULL; }

static motor_rt_t make_sample_motor(uint32_t node_id, uint16_t type) {
	motor_rt_t m;
	memset(&m, 0, sizeof(m));
	m.node_id = node_id;
	m.type_id = type;
	m.pwm_pin = 1;
	m.pwm_ch = 0;
	m.pwm_freq = 50;
	m.min_us = 1000;
	m.max_us = 2000;
	m.neutral_us = 1500;
	m.timeout_ms = 20;
	return m;
}

TEST(motor_registry_add_records_time_from_hw) {
	motor_registry_clear();
	mock_hw_t mock;
	mock_hw_setup(&mock);
	mock.now_value = 1234;

	motor_rt_t m = make_sample_motor(1, MOTOR_TYPE_CONT);
	ASSERT_EQ(motor_registry_add(&m), 0);

	motor_rt_t *stored = NULL;
	ASSERT_EQ(motor_registry_find(1, &stored), 0);
	ASSERT(stored != NULL);
	ASSERT_EQ(stored->last_cmd_ms, (uint32_t)1234);

	mock_hw_teardown();
}

TEST(motor_set_speed_invokes_hw_for_hbridge) {
	motor_registry_clear();
	mock_hw_t mock;
	mock_hw_setup(&mock);
	mock.now_value = 10;

	motor_rt_t m = make_sample_motor(2, MOTOR_TYPE_HBR);
	m.in1_pin = 4;
	m.in2_pin = 5;
	m.pwm_freq = 1000;
	ASSERT_EQ(motor_registry_add(&m), 0);

	ASSERT_EQ(motor_set_speed(2, 1.5f), 0);
	ASSERT_EQ(mock.ensure_calls, 1);
	ASSERT_EQ(mock.bind_calls, 1);
	ASSERT_EQ(mock.hbridge_calls, 1);
	ASSERT(mock.last_forward);
	ASSERT(!mock.last_brake);
	ASSERT_EQ(mock.duty_calls, 1);
	EXPECT_APPROX_EQ(mock.last_duty_ratio, 1.0f, 0.0001f);

	mock_hw_teardown();
}

TEST(motor_tick_all_stops_continuous_servo_on_timeout) {
	motor_registry_clear();
	mock_hw_t mock;
	mock_hw_setup(&mock);
	mock.now_value = 20;

	motor_rt_t m = make_sample_motor(3, MOTOR_TYPE_CONT);
	m.timeout_ms = 5;
	ASSERT_EQ(motor_registry_add(&m), 0);

	motor_rt_t *stored = NULL;
	ASSERT_EQ(motor_registry_find(3, &stored), 0);
	ASSERT(stored != NULL);

	uint32_t expire = stored->last_cmd_ms + stored->timeout_ms + 1;
	motor_tick_all(expire);

	ASSERT_EQ(mock.pulse_calls, 1);
	ASSERT_EQ(mock.last_pulse_us, (uint16_t)1500);

	mock_hw_teardown();
}
