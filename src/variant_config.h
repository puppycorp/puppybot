#ifndef __VARIANT_CONFIG_H__
#define __VARIANT_CONFIG_H__

#ifdef ESP_PLATFORM
#include "driver/gpio.h"
#include "driver/ledc.h"
#else
#include "espidf_stubs.h"
#endif
#include <stdint.h>

#define VARIANT_PUPPYBOT 1
#define VARIANT_PUPPYARM 2

#if defined(PUPPY_VARIANT_PUPPYARM)
#define PUPPY_VARIANT VARIANT_PUPPYARM
#else
#define PUPPY_VARIANT VARIANT_PUPPYBOT
#endif

#if PUPPY_VARIANT == VARIANT_PUPPYARM
#define PUPPY_HOSTNAME "puppyarm"
#define PUPPY_INSTANCE_NAME "PuppyArm"
#define PUPPY_SERVO_COUNT 4
#define PUPPY_HAS_DRIVE_MOTORS 0
#define PUPPY_STEERING_SERVO_ID 0
#define PUPPY_STEERING_CENTER_ANGLE 90
static const uint8_t puppy_servo_boot_angles[PUPPY_SERVO_COUNT] = {90, 90, 90,
                                                                   90};
static const struct {
	gpio_num_t gpio;
	ledc_channel_t channel;
} puppy_servo_outputs[PUPPY_SERVO_COUNT] = {
    {GPIO_NUM_13, LEDC_CHANNEL_2},
    {GPIO_NUM_21, LEDC_CHANNEL_3},
    {GPIO_NUM_22, LEDC_CHANNEL_4},
    {GPIO_NUM_23, LEDC_CHANNEL_5},
};
#else
#define PUPPY_HOSTNAME "puppybot"
#define PUPPY_INSTANCE_NAME "PuppyBot"
#define PUPPY_SERVO_COUNT 4
#define PUPPY_HAS_DRIVE_MOTORS 1
#define PUPPY_STEERING_SERVO_ID 0
#define PUPPY_STEERING_CENTER_ANGLE 88
static const uint8_t puppy_servo_boot_angles[PUPPY_SERVO_COUNT] = {88, 90, 90,
                                                                   90};
static const struct {
	gpio_num_t gpio;
	ledc_channel_t channel;
} puppy_servo_outputs[PUPPY_SERVO_COUNT] = {
    {GPIO_NUM_13, LEDC_CHANNEL_2},
    {GPIO_NUM_21, LEDC_CHANNEL_3},
    {GPIO_NUM_22, LEDC_CHANNEL_4},
    {GPIO_NUM_23, LEDC_CHANNEL_5},
};
#endif

static inline uint8_t puppy_servo_boot_angle(uint8_t servo_id) {
	if (servo_id >= PUPPY_SERVO_COUNT) {
		return 90;
	}
	return puppy_servo_boot_angles[servo_id];
}

#endif // __VARIANT_CONFIG_H__
