#include "puppyarm/puppyarm.h"

#include <string.h>

#include "motor_hw.h"

typedef struct {
	uint8_t uart_port;
} puppyarm_motor_hw_bus_t;

static puppyarm_controller_t g_puppyarm;
static puppyarm_motor_hw_bus_t g_bus_ctx;
static bool g_initialized = false;

static int hw_enable_wheel_mode(void *ctx, uint8_t servo_id) {
	puppyarm_motor_hw_bus_t *bus = (puppyarm_motor_hw_bus_t *)ctx;
	if (!bus)
		return -1;
	motor_hw_smartbus_set_mode(bus->uart_port, servo_id, 1);
	return 0;
}

static int hw_set_wheel_speed(void *ctx, uint8_t servo_id, int16_t speed,
                              uint8_t acc) {
	puppyarm_motor_hw_bus_t *bus = (puppyarm_motor_hw_bus_t *)ctx;
	if (!bus)
		return -1;
	int32_t mag = speed < 0 ? -(int32_t)speed : (int32_t)speed;
	if (mag > 1000)
		mag = 1000;
	int32_t raw = mag;
	if (speed < 0)
		raw |= (1 << 15);
	motor_hw_smartbus_set_wheel_speed(bus->uart_port, servo_id, (int16_t)raw,
	                                  acc);
	return 0;
}

static int hw_read_position(void *ctx, uint8_t servo_id,
                            uint16_t *pos_raw_out) {
	puppyarm_motor_hw_bus_t *bus = (puppyarm_motor_hw_bus_t *)ctx;
	if (!bus)
		return -1;
	return motor_hw_smartbus_read_position(bus->uart_port, servo_id,
	                                       pos_raw_out);
}

static void init_joint(puppyarm_joint_calibration_t *joint, uint8_t servo_id,
                       int32_t tick_min, int32_t tick_max, float sign,
                       float drive_sign, int32_t zero_tick,
                       float target_angle_rad) {
	memset(joint, 0, sizeof(*joint));
	joint->servo_id = servo_id;
	joint->tick_min = tick_min;
	joint->tick_max = tick_max;
	joint->raw_tick_min = tick_min;
	joint->raw_tick_max = tick_max;
	joint->sign = sign;
	joint->drive_sign = drive_sign;
	joint->zero_offset_rad = puppyarm_zero_offset_from_reference(
	    zero_tick, tick_min, tick_max, sign, target_angle_rad);
	joint->limit_enabled = true;
}

void puppyarm_profile_get_default(puppyarm_profile_t *out) {
	if (!out)
		return;
	memset(out, 0, sizeof(*out));
	out->l1_mm = 150.0f;
	out->l2_mm = 152.0f;
	out->l3_mm = 130.0f;
	out->z_origin_mm = 60.0f;
	out->tool_phi_rad = -PUPPYARM_PI / 2.0f;

	init_joint(&out->joints[PUPPYARM_JOINT_YAW], 1, -1400, 1400, 1.0f,
	           1.0f, -1400, 0.0f);
	init_joint(&out->joints[PUPPYARM_JOINT_SHOULDER], 2, 100, 1000, -1.0f,
	           1.0f, 530, PUPPYARM_PI / 2.0f);
	init_joint(&out->joints[PUPPYARM_JOINT_ELBOW], 3, 2200, 3600, -1.0f,
	           1.0f, 3565, 0.0f);
	init_joint(&out->joints[PUPPYARM_JOINT_TIP], 4, 500, 3000, 1.0f, 1.0f,
	           1783, 0.0f);
}

int puppyarm_init_default(uint8_t uart_port, int tx_pin, int rx_pin,
                          uint32_t baud_rate, uint32_t now_ms) {
	puppyarm_profile_t profile;
	puppyarm_profile_get_default(&profile);
	if (motor_hw_configure_smartbus(uart_port, tx_pin, rx_pin, baud_rate) != 0)
		return -1;
	g_bus_ctx.uart_port = uart_port;
	puppyarm_bus_t bus = {
	    .ctx = &g_bus_ctx,
	    .enable_wheel_mode = hw_enable_wheel_mode,
	    .set_wheel_speed = hw_set_wheel_speed,
	    .read_position = hw_read_position,
	};
	int rc = puppyarm_controller_init(&g_puppyarm, &profile, &bus, now_ms);
	g_initialized = rc == 0;
	return rc;
}

int puppyarm_start(uint32_t now_ms) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_start(&g_puppyarm, now_ms);
}

int puppyarm_step(uint32_t now_ms) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_step(&g_puppyarm, now_ms);
}

void puppyarm_stop(uint32_t now_ms) {
	if (g_initialized)
		puppyarm_controller_stop_all(&g_puppyarm, now_ms);
}

int puppyarm_set_speed(uint16_t speed) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_set_speed(&g_puppyarm, speed);
}

int puppyarm_stop_joint(uint8_t joint, uint32_t now_ms) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_stop_joint(&g_puppyarm, joint, now_ms);
}

void puppyarm_clear_faults(void) {
	if (g_initialized)
		puppyarm_controller_clear_faults(&g_puppyarm);
}

int puppyarm_clear_joint_fault(uint8_t joint) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_clear_joint_fault(&g_puppyarm, joint);
}

int puppyarm_goto_ticks(const int32_t ticks[PUPPYARM_JOINT_COUNT],
                        uint16_t speed, uint32_t now_ms) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_goto_ticks(&g_puppyarm, ticks, speed, now_ms);
}

int puppyarm_goto_angles(const float angles_rad[PUPPYARM_JOINT_COUNT],
                         uint16_t speed, uint32_t now_ms) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_goto_angles(&g_puppyarm, angles_rad, speed,
	                                       now_ms);
}

int puppyarm_goto_coords(float x_mm, float y_mm, float z_mm, uint16_t speed,
                         uint32_t now_ms) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_goto_coords(&g_puppyarm, x_mm, y_mm, z_mm,
	                                       speed, now_ms);
}

int puppyarm_jog(uint8_t joint, int8_t direction, uint16_t speed,
                 uint32_t now_ms) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_jog(&g_puppyarm, joint, direction, speed,
	                               now_ms);
}

int puppyarm_hold(uint16_t speed, uint32_t now_ms) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_hold(&g_puppyarm, speed, now_ms);
}

int puppyarm_set_joint_tick(uint8_t joint, int32_t tick, uint16_t speed,
                            uint32_t now_ms) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_set_joint_tick(&g_puppyarm, joint, tick, speed,
	                                          now_ms);
}

int puppyarm_set_tick_limits(uint8_t joint, int32_t min_tick,
                             int32_t max_tick) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_set_tick_limits(&g_puppyarm, joint, min_tick,
	                                           max_tick);
}

int puppyarm_set_tick_limits_enabled(uint8_t joint, bool enabled) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_set_tick_limits_enabled(&g_puppyarm, joint,
	                                                   enabled);
}

int puppyarm_move_relative(float dx_mm, float dy_mm, uint16_t speed,
                           uint32_t now_ms) {
	if (!g_initialized)
		return -1;
	return puppyarm_controller_move_relative(&g_puppyarm, dx_mm, dy_mm, speed,
	                                         now_ms);
}

const puppyarm_controller_t *puppyarm_controller(void) {
	return g_initialized ? &g_puppyarm : NULL;
}
