#include "motor_runtime.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "motor_hw.h"
#include "utility.h"

#define MAX_MOTORS 16
#define SMARTBUS_SPEED_SIGN_BIT 15

static motor_rt_t g_motors[MAX_MOTORS];
static int g_mcount = 0;

int motor_registry_add(const motor_rt_t *m) {
	if (!m)
		return -1;
	if (g_mcount >= MAX_MOTORS)
		return -2;
	g_motors[g_mcount] = *m;
	g_motors[g_mcount].last_cmd_ms = now_ms();
	g_motors[g_mcount].last_cmd_val = 0.0f;
	g_mcount++;
	return 0;
}

int motor_registry_find(uint32_t node_id, motor_rt_t **out) {
	if (!out)
		return -1;
	for (int i = 0; i < g_mcount; ++i) {
		if (g_motors[i].node_id == node_id) {
			*out = &g_motors[i];
			return 0;
		}
	}
	return -2;
}

void motor_registry_clear(void) {
	memset(g_motors, 0, sizeof(g_motors));
	g_mcount = 0;
}

int motor_count(void) { return g_mcount; }

motor_rt_t *motor_at(int idx) {
	if (idx < 0 || idx >= g_mcount)
		return NULL;
	return &g_motors[idx];
}

static void apply_continuous_servo(motor_rt_t *m, float speed) {
	if (!m)
		return;
	if (m->invert)
		speed = -speed;
	if (m->max_speed_x100) {
		float cap = m->max_speed_x100 / 100.0f;
		if (speed > cap)
			speed = cap;
		if (speed < -cap)
			speed = -cap;
	}
	uint16_t span = (uint16_t)((m->max_us - m->min_us) / 2);
	int32_t us = (int32_t)m->neutral_us + (int32_t)(speed * (int32_t)span);
	if (us < m->min_us)
		us = m->min_us;
	if (us > m->max_us)
		us = m->max_us;

	motor_hw_set_pwm_pulse_us(m->pwm_ch, m->pwm_freq, (uint16_t)us);
}

static void apply_angle_servo(motor_rt_t *m, float deg) {
	if (!m)
		return;
	float dmin = m->deg_min_x10 / 10.0f;
	float dmax = m->deg_max_x10 / 10.0f;
	if (deg < dmin)
		deg = dmin;
	if (deg > dmax)
		deg = dmax;
	float range = dmax - dmin;
	if (range < 1e-6f)
		range = 1e-6f;
	float t = (deg - dmin) / range;
	uint16_t us = (uint16_t)(m->min_us + t * (m->max_us - m->min_us));

	motor_hw_set_pwm_pulse_us(m->pwm_ch, m->pwm_freq, us);
}

static void apply_smart_servo(motor_rt_t *m, float deg, uint16_t duration_ms) {
	if (!m)
		return;
	if (m->smart_wheel_mode) {
		motor_hw_smartbus_set_mode(m->smart_uart_port, (uint8_t)m->node_id, 0);
		m->smart_wheel_mode = false;
	}
	float dmin = m->deg_min_x10 / 10.0f;
	float dmax = m->deg_max_x10 / 10.0f;
	if (deg < dmin)
		deg = dmin;
	if (deg > dmax)
		deg = dmax;
	uint16_t angle_x10 = (uint16_t)lroundf(deg * 10.0f);
	motor_hw_smartbus_move(m->smart_uart_port, (uint8_t)m->node_id, angle_x10,
	                       duration_ms);
}

static void apply_smart_wheel(motor_rt_t *m, float speed) {
	if (!m)
		return;
	if (m->invert)
		speed = -speed;
	if (m->max_speed_x100) {
		float cap = m->max_speed_x100 / 100.0f;
		if (speed > cap)
			speed = cap;
		if (speed < -cap)
			speed = -cap;
	}

	if (!m->smart_wheel_mode) {
		motor_hw_smartbus_set_mode(m->smart_uart_port, (uint8_t)m->node_id, 1);
		m->smart_wheel_mode = true;
	}

	float abs_speed = fabsf(speed);
	if (abs_speed > 1.0f)
		abs_speed = 1.0f;
	int32_t mag = (int32_t)lroundf(abs_speed * 1000.0f);
	if (mag > 1000)
		mag = 1000;
	int32_t raw = mag;
	if (speed < 0.0f)
		raw |= (1 << SMARTBUS_SPEED_SIGN_BIT);

	motor_hw_smartbus_set_wheel_speed(m->smart_uart_port, (uint8_t)m->node_id,
	                                  (int16_t)raw, 0);
}

static void apply_hbridge_dc(motor_rt_t *m, float speed) {
	if (!m)
		return;
	if (m->invert)
		speed = -speed;
	if (speed > 1.f)
		speed = 1.f;
	if (speed < -1.f)
		speed = -1.f;

	motor_hw_ensure_pwm(m->pwm_ch, m->pwm_freq);
	if (m->pwm_pin >= 0)
		motor_hw_bind_pwm_pin(m->pwm_ch, m->pwm_pin);

	motor_hw_configure_hbridge(m->in1_pin, m->in2_pin, speed >= 0.f,
	                           m->brake_mode != 0);
	motor_hw_set_pwm_duty(m->pwm_ch, fabsf(speed));
}

int motor_set_speed(uint32_t node_id, float speed) {
	motor_rt_t *m = NULL;
	if (motor_registry_find(node_id, &m) != 0 || !m)
		return -1;
	switch (m->type_id) {
	case MOTOR_TYPE_CONT:
		apply_continuous_servo(m, speed);
		break;
	case MOTOR_TYPE_HBR:
		apply_hbridge_dc(m, speed);
		break;
	default:
		return -2;
	}
	m->last_cmd_val = speed;
	m->last_cmd_ms = now_ms();
	return 0;
}

int motor_set_angle(uint32_t node_id, float deg) {
	motor_rt_t *m = NULL;
	if (motor_registry_find(node_id, &m) != 0 || !m)
		return -1;
	if (m->type_id == MOTOR_TYPE_SMART) {
		apply_smart_servo(m, deg, 0);
	} else if (m->type_id == MOTOR_TYPE_ANGLE) {
		apply_angle_servo(m, deg);
	} else {
		return -2;
	}
	m->last_cmd_val = deg;
	m->last_cmd_ms = now_ms();
	return 0;
}

int motor_set_smart_angle(uint32_t node_id, float deg, uint16_t duration_ms) {
	motor_rt_t *m = NULL;
	if (motor_registry_find(node_id, &m) != 0 || !m)
		return -1;
	if (m->type_id != MOTOR_TYPE_SMART)
		return -2;
	apply_smart_servo(m, deg, duration_ms);
	m->last_cmd_val = deg;
	m->last_cmd_ms = now_ms();
	return 0;
}

int motor_set_smart_speed(uint32_t node_id, float speed) {
	motor_rt_t *m = NULL;
	if (motor_registry_find(node_id, &m) != 0 || !m)
		return -1;
	if (m->type_id != MOTOR_TYPE_SMART)
		return -2;
	apply_smart_wheel(m, speed);
	m->last_cmd_val = speed;
	m->last_cmd_ms = now_ms();
	return 0;
}

int motor_stop(uint32_t node_id) {
	motor_rt_t *m = NULL;
	if (motor_registry_find(node_id, &m) != 0 || !m)
		return -1;
	if (m->type_id == MOTOR_TYPE_CONT && m->neutral_us) {
		motor_hw_set_pwm_pulse_us(m->pwm_ch, m->pwm_freq, m->neutral_us);
		m->last_cmd_val = 0.0f;
	} else if (m->type_id == MOTOR_TYPE_HBR) {
		motor_hw_configure_hbridge(m->in1_pin, m->in2_pin, true, false);
		motor_hw_set_pwm_duty(m->pwm_ch, 0.0f);
		m->last_cmd_val = 0.0f;
	} else if (m->type_id == MOTOR_TYPE_ANGLE) {
		apply_angle_servo(m, m->last_cmd_val);
	} else if (m->type_id == MOTOR_TYPE_SMART) {
		if (m->smart_wheel_mode) {
			apply_smart_wheel(m, 0.0f);
		} else {
			apply_smart_servo(m, m->last_cmd_val, 0);
		}
	}
	m->last_cmd_ms = now_ms();
	return 0;
}

int motor_get_smart_position(uint32_t node_id, float *deg_out) {
	if (!deg_out)
		return -1;
	motor_rt_t *m = NULL;
	if (motor_registry_find(node_id, &m) != 0 || !m)
		return -2;
	if (m->type_id != MOTOR_TYPE_SMART)
		return -3;

	uint16_t pos_raw = 0;
	int r = motor_hw_smartbus_read_position(m->smart_uart_port,
	                                        (uint8_t)m->node_id, &pos_raw);
	if (r != 0)
		return r;

	*deg_out = ((float)pos_raw / 1000.0f) * 240.0f;
	return 0;
}

void motor_tick_all(uint32_t now_ms_val) {
	for (int i = 0; i < g_mcount; ++i) {
		motor_rt_t *m = &g_motors[i];
		if (m->timeout_ms == 0)
			continue;
		if ((uint32_t)(now_ms_val - m->last_cmd_ms) > m->timeout_ms) {
			if (m->type_id == MOTOR_TYPE_CONT && m->neutral_us) {
				motor_hw_set_pwm_pulse_us(m->pwm_ch, m->pwm_freq,
				                          m->neutral_us);
				m->last_cmd_val = 0.0f;
			} else if (m->type_id == MOTOR_TYPE_HBR) {
				motor_hw_configure_hbridge(m->in1_pin, m->in2_pin, true, false);
				motor_hw_set_pwm_duty(m->pwm_ch, 0.0f);
				m->last_cmd_val = 0.0f;
			}
			m->last_cmd_ms = now_ms_val;
		}
	}
}
