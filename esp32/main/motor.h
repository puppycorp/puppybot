#ifndef __MOTOR_H__
#define __MOTOR_H__

#include "driver/gpio.h"
#include "driver/ledc.h"
#include <stdint.h>

// ---------------- GPIO Definitions ----------------

// Left drive motor
#define IN1_GPIO GPIO_NUM_25
#define IN2_GPIO GPIO_NUM_26
#define ENA_GPIO GPIO_NUM_33

// Right drive motor
#define IN3_GPIO GPIO_NUM_27
#define IN4_GPIO GPIO_NUM_14
#define ENB_GPIO GPIO_NUM_32

// ---------------- PWM Configuration ----------------

#define LEDC_MODE LEDC_HIGH_SPEED_MODE
#define LEDC_TIMER LEDC_TIMER_0
#define LEDC_DUTY_RES LEDC_TIMER_8_BIT
#define LEDC_FREQUENCY 1000 // 1 kHz for DC motors

#define ENA_CHANNEL LEDC_CHANNEL_0
#define ENB_CHANNEL LEDC_CHANNEL_1

// Servo runs on a separate timer/channel
#define SERVO_TIMER LEDC_TIMER_1
#define SERVO_DUTY_RES LEDC_TIMER_16_BIT
#define SERVO_FREQUENCY 50

typedef struct {
	gpio_num_t gpio;
	ledc_channel_t channel;
} servo_output_t;

#include "variant_config.h"

#define SERVO_COUNT PUPPY_SERVO_COUNT

static inline servo_output_t get_servo_output(int index) {
	servo_output_t output = {
	    .gpio = puppy_servo_outputs[index].gpio,
	    .channel = puppy_servo_outputs[index].channel,
	};
	return output;
}

// ---------------- Servo angle conversion ----------------

// Safer angle clamp + configurable pulse range
static inline uint32_t angle_to_duty(uint32_t angle_deg) {
	if (angle_deg > 180) angle_deg = 180; // clamp

	const uint32_t min_pulse = 1000;  // µs
	const uint32_t max_pulse = 2000;  // µs  (consider making these per-servo)
	const uint32_t period_us = 1000000 / SERVO_FREQUENCY; // 20000 at 50 Hz
	const uint32_t max_duty  = (1U << SERVO_DUTY_RES) - 1;

	uint32_t pulse = min_pulse + (angle_deg * (max_pulse - min_pulse)) / 180;
	// round instead of truncate
	uint64_t num = (uint64_t)pulse * max_duty + (period_us/2);
	return (uint32_t)(num / period_us);
}

// ---------------- GPIO Init ----------------

static inline void motor_gpio_init() {
	uint64_t servo_mask = 0;
	for (int i = 0; i < SERVO_COUNT; ++i) {
		servo_output_t output = get_servo_output(i);
		servo_mask |= (1ULL << output.gpio);
	}

	gpio_config_t io_conf = {
	    .pin_bit_mask = (1ULL << IN1_GPIO) | (1ULL << IN2_GPIO) |
	                    (1ULL << IN3_GPIO) | (1ULL << IN4_GPIO) | servo_mask,
	    .mode = GPIO_MODE_OUTPUT,
	    .pull_up_en = GPIO_PULLUP_DISABLE,
	    .pull_down_en = GPIO_PULLDOWN_DISABLE,
	    .intr_type = GPIO_INTR_DISABLE};
	gpio_config(&io_conf);
}

// ---------------- PWM Init ----------------

static inline void motor_pwm_init() {
	ledc_timer_config_t ledc_timer = {.speed_mode = LEDC_MODE,
	                                  .timer_num = LEDC_TIMER,
	                                  .duty_resolution = LEDC_DUTY_RES,
	                                  .freq_hz = LEDC_FREQUENCY,
	                                  .clk_cfg = LEDC_AUTO_CLK};
	ledc_timer_config(&ledc_timer);

	ledc_channel_config_t channels[] = {
	    {.speed_mode = LEDC_MODE,
	     .channel = ENA_CHANNEL,
	     .timer_sel = LEDC_TIMER,
	     .intr_type = LEDC_INTR_DISABLE,
	     .gpio_num = ENA_GPIO,
	     .duty = 0,
	     .hpoint = 0},

	    {.speed_mode = LEDC_MODE,
	     .channel = ENB_CHANNEL,
	     .timer_sel = LEDC_TIMER,
	     .intr_type = LEDC_INTR_DISABLE,
	     .gpio_num = ENB_GPIO,
	     .duty = 0,
	     .hpoint = 0},

	};

	for (int i = 0; i < 2; i++) {
		ledc_channel_config(&channels[i]);
	}

	// Servo PWM
	ledc_timer_config_t servo_timer = {.speed_mode = LEDC_MODE,
	                                   .timer_num = SERVO_TIMER,
	                                   .duty_resolution = SERVO_DUTY_RES,
	                                   .freq_hz = SERVO_FREQUENCY,
	                                   .clk_cfg = LEDC_AUTO_CLK};
	ledc_timer_config(&servo_timer);

	for (int i = 0; i < SERVO_COUNT; ++i) {
		servo_output_t output = get_servo_output(i);
		ledc_channel_config_t servo_channel = {.speed_mode = LEDC_MODE,
		                                       .channel = output.channel,
		                                       .timer_sel = SERVO_TIMER,
		                                       .intr_type = LEDC_INTR_DISABLE,
		                                       .gpio_num = output.gpio,
		                                       .duty = 0,
		                                       .hpoint = 0};
		ledc_channel_config(&servo_channel);

		// Immediately go to center to avoid twitching on first command
		uint32_t center = angle_to_duty(90);
		ledc_set_duty(LEDC_MODE, output.channel, center);
		ledc_update_duty(LEDC_MODE, output.channel);
	}
}

// ---------------- Motor Control Functions ----------------

#define DEFINE_MOTOR_FUNCTIONS(NAME, INx, INy, CHANNEL)                        \
	static inline void NAME##_forward(uint8_t speed) {                         \
		gpio_set_level(INx, 1);                                                \
		gpio_set_level(INy, 0);                                                \
		ledc_set_duty(LEDC_MODE, CHANNEL, speed);                              \
		ledc_update_duty(LEDC_MODE, CHANNEL);                                  \
	}                                                                          \
	static inline void NAME##_backward(uint8_t speed) {                        \
		gpio_set_level(INx, 0);                                                \
		gpio_set_level(INy, 1);                                                \
		ledc_set_duty(LEDC_MODE, CHANNEL, speed);                              \
		ledc_update_duty(LEDC_MODE, CHANNEL);                                  \
	}                                                                          \
	static inline void NAME##_stop() {                                         \
		gpio_set_level(INx, 0);                                                \
		gpio_set_level(INy, 0);                                                \
		ledc_set_duty(LEDC_MODE, CHANNEL, 0);                                  \
		ledc_update_duty(LEDC_MODE, CHANNEL);                                  \
	}

// Create functions for each motor
DEFINE_MOTOR_FUNCTIONS(motorA, IN1_GPIO, IN2_GPIO, ENA_CHANNEL)
DEFINE_MOTOR_FUNCTIONS(motorB, IN3_GPIO, IN4_GPIO, ENB_CHANNEL)

static inline void servo_set_angle(uint8_t servo_id, uint32_t angle) {
	if (servo_id >= SERVO_COUNT) return;
	if (angle > 180) angle = 180;

	servo_output_t output = get_servo_output(servo_id);
	uint32_t duty = angle_to_duty(angle);
	ledc_set_duty(LEDC_MODE, output.channel, duty);
	ledc_update_duty(LEDC_MODE, output.channel);
}

#endif // __MOTOR_H__
