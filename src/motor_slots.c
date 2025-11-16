#include "motor_slots.h"

#include "motor_hw.h"
#include <stddef.h>

#define MAX_DRIVE_MOTORS 4
#define MAX_SERVO_MOTORS 8

static motor_rt_t *g_drive_motors[MAX_DRIVE_MOTORS];
static int g_drive_count = 0;

static motor_rt_t *g_servo_motors[MAX_SERVO_MOTORS];
static int g_servo_count = 0;

void motor_slots_reset(void) {
	g_drive_count = 0;
	g_servo_count = 0;
	for (int i = 0; i < MAX_DRIVE_MOTORS; ++i)
		g_drive_motors[i] = NULL;
	for (int i = 0; i < MAX_SERVO_MOTORS; ++i)
		g_servo_motors[i] = NULL;
}

void motor_slots_register(motor_rt_t *motor) {
	if (!motor) return;

	if (motor->pwm_pin >= 0) {
		motor_hw_ensure_pwm(motor->pwm_ch, motor->pwm_freq);
		motor_hw_bind_pwm_pin(motor->pwm_ch, motor->pwm_pin);
	}

	switch (motor->type_id) {
	case MOTOR_TYPE_HBR:
	case MOTOR_TYPE_CONT:
		if (g_drive_count < MAX_DRIVE_MOTORS)
			g_drive_motors[g_drive_count++] = motor;
		break;
	case MOTOR_TYPE_ANGLE:
		if (g_servo_count < MAX_SERVO_MOTORS)
			g_servo_motors[g_servo_count++] = motor;
		break;
	default:
		break;
	}
}

motor_rt_t *motor_slots_drive(int idx) {
	if (idx < 0 || idx >= g_drive_count)
		return NULL;
	return g_drive_motors[idx];
}

int motor_slots_drive_count(void) { return g_drive_count; }

motor_rt_t *motor_slots_servo(int idx) {
	if (idx < 0 || idx >= g_servo_count)
		return NULL;
	return g_servo_motors[idx];
}

int motor_slots_servo_count(void) { return g_servo_count; }

float motor_slots_servo_boot_angle(int idx) {
	motor_rt_t *m = motor_slots_servo(idx);
	if (!m)
		return 90.0f;
	float dmin = m->deg_min_x10 / 10.0f;
	float dmax = m->deg_max_x10 / 10.0f;
	if (dmax <= dmin)
		return dmin;
	return dmin + (dmax - dmin) * 0.5f;
}
