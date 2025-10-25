#ifndef PBCL_TAGS_H
#define PBCL_TAGS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
	PBCL_MOTOR_TYPE_ANGLE = 1,
	PBCL_MOTOR_TYPE_CONT = 2,
	PBCL_MOTOR_TYPE_HBR = 3,
	PBCL_MOTOR_TYPE_SMART = 4
};

enum {
	PBCL_T_M_PWM = 10,
	PBCL_T_M_HBRIDGE = 11,
	PBCL_T_M_ANALOG_FB = 12,
	PBCL_T_M_LIMITS = 13
};

typedef struct __attribute__((packed)) {
	int8_t pin;
	uint8_t ch;
	uint16_t freq_hz;
	uint16_t min_us;
	uint16_t max_us;
	uint16_t neutral_us;
	uint8_t invert;
	uint8_t reserved;
} pbcl_t_motor_pwm;

typedef struct __attribute__((packed)) {
	int8_t in1;
	int8_t in2;
	uint8_t brake_mode;
	uint8_t reserved;
} pbcl_t_motor_hbridge;

typedef struct __attribute__((packed)) {
	int8_t adc_pin;
	uint8_t reserved0;
	uint16_t adc_min;
	uint16_t adc_max;
	int16_t deg_min_x10;
	int16_t deg_max_x10;
} pbcl_t_motor_analogfb;

typedef struct __attribute__((packed)) {
	uint16_t max_speed_x100;
	uint16_t current_limit_ma;
} pbcl_t_motor_limits;

#ifdef __cplusplus
}
#endif

#endif // PBCL_TAGS_H
