#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "motor_hw.h"

// ---- Motor types (match PBCL_MOTOR_* in pbcl_tags.h) ----
enum {
	MOTOR_TYPE_ANGLE = 1,
	MOTOR_TYPE_CONT = 2,
	MOTOR_TYPE_HBR = 3,
	MOTOR_TYPE_SMART = 4
};

typedef struct {
	uint32_t node_id;
	uint16_t type_id;
	char name[24];

	int8_t pwm_pin;
	uint8_t pwm_ch;
	uint16_t pwm_freq;
	uint16_t min_us;
	uint16_t max_us;
	uint16_t neutral_us;
	uint8_t invert;

	int8_t in1_pin;
	int8_t in2_pin;
	uint8_t brake_mode;

	int8_t adc_pin;
	uint16_t adc_min;
	uint16_t adc_max;
	int16_t deg_min_x10;
	int16_t deg_max_x10;

	uint16_t timeout_ms;
	uint16_t max_speed_x100;

	float last_cmd_val;
	uint32_t last_cmd_ms;
} motor_rt_t;

int motor_registry_add(const motor_rt_t *m);
int motor_registry_find(uint32_t node_id, motor_rt_t **out);
void motor_registry_clear(void);
int motor_count(void);
motor_rt_t *motor_at(int idx);

void motor_tick_all(uint32_t now_ms);

int motor_set_speed(uint32_t node_id, float speed_m1_p1);
int motor_set_angle(uint32_t node_id, float deg);
int motor_stop(uint32_t node_id);
