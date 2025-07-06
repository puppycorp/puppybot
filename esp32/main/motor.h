#ifndef __MOTOR_H__
#define __MOTOR_H__

#include "driver/gpio.h"
#include "driver/ledc.h"

// ---------------- GPIO Definitions ----------------

// Left drive motor
#define IN1_GPIO GPIO_NUM_25
#define IN2_GPIO GPIO_NUM_26
#define ENA_GPIO GPIO_NUM_33

// Right drive motor
#define IN3_GPIO GPIO_NUM_27
#define IN4_GPIO GPIO_NUM_14
#define ENB_GPIO GPIO_NUM_32

// Servo for steering
#define SERVO_GPIO GPIO_NUM_13

// ---------------- PWM Configuration ----------------

#define LEDC_MODE LEDC_HIGH_SPEED_MODE
#define LEDC_TIMER LEDC_TIMER_0
#define LEDC_DUTY_RES LEDC_TIMER_8_BIT
#define LEDC_FREQUENCY 1000 // 1 kHz for DC motors

#define ENA_CHANNEL LEDC_CHANNEL_0
#define ENB_CHANNEL LEDC_CHANNEL_1

// Servo runs on a separate timer/channel
#define SERVO_TIMER LEDC_TIMER_1
#define SERVO_CHANNEL LEDC_CHANNEL_2
#define SERVO_DUTY_RES LEDC_TIMER_16_BIT
#define SERVO_FREQUENCY 50

#define ENA_CHANNEL LEDC_CHANNEL_0
#define ENB_CHANNEL LEDC_CHANNEL_1
#define ENC_CHANNEL LEDC_CHANNEL_2
#define END_CHANNEL LEDC_CHANNEL_3

// ---------------- GPIO Init ----------------

static inline void motor_gpio_init() {
	gpio_config_t io_conf = {.pin_bit_mask =
	                             (1ULL << IN1_GPIO) | (1ULL << IN2_GPIO) |
	                             (1ULL << IN3_GPIO) | (1ULL << IN4_GPIO) |
	                             (1ULL << SERVO_GPIO),
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

	ledc_channel_config_t servo_channel = {.speed_mode = LEDC_MODE,
	                                       .channel = SERVO_CHANNEL,
	                                       .timer_sel = SERVO_TIMER,
	                                       .intr_type = LEDC_INTR_DISABLE,
	                                       .gpio_num = SERVO_GPIO,
	                                       .duty = 0,
	                                       .hpoint = 0};
	ledc_channel_config(&servo_channel);
}

// ---------------- Motor Control Functions ----------------

#define DEFINE_MOTOR_FUNCTIONS(NAME, INx, INy, CHANNEL)                        \
	static inline void NAME##_forward(uint8_t speed) {                        \
		gpio_set_level(INx, 1);                                                \
		gpio_set_level(INy, 0);                                                \
		ledc_set_duty(LEDC_MODE, CHANNEL, speed);                              \
		ledc_update_duty(LEDC_MODE, CHANNEL);                                  \
	}                                                                          \
	static inline void NAME##_backward(uint8_t speed) {                       \
		gpio_set_level(INx, 0);                                                \
		gpio_set_level(INy, 1);                                                \
		ledc_set_duty(LEDC_MODE, CHANNEL, speed);                              \
		ledc_update_duty(LEDC_MODE, CHANNEL);                                  \
	}                                                                          \
	static inline void NAME##_stop() {                                        \
		gpio_set_level(INx, 0);                                                \
		gpio_set_level(INy, 0);                                                \
		ledc_set_duty(LEDC_MODE, CHANNEL, 0);                                  \
		ledc_update_duty(LEDC_MODE, CHANNEL);                                  \
	}

// Create functions for each motor
DEFINE_MOTOR_FUNCTIONS(motorA, IN1_GPIO, IN2_GPIO, ENA_CHANNEL)
DEFINE_MOTOR_FUNCTIONS(motorB, IN3_GPIO, IN4_GPIO, ENB_CHANNEL)

static inline uint32_t angle_to_duty(uint32_t angle) {
	const uint32_t min_pulse = 500;  // microseconds
	const uint32_t max_pulse = 2500; // microseconds
	uint32_t pulse = min_pulse + (angle * (max_pulse - min_pulse)) / 180;
	uint32_t max_duty = (1 << SERVO_DUTY_RES) - 1;
	return (pulse * max_duty) / (1000000 / SERVO_FREQUENCY);
}

static inline void servo_set_angle(uint32_t angle) {
	uint32_t duty = angle_to_duty(angle);
	ledc_set_duty(LEDC_MODE, SERVO_CHANNEL, duty);
	ledc_update_duty(LEDC_MODE, SERVO_CHANNEL);
}

#endif // __MOTOR_H__
