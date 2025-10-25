#include "test.h"

#include "espidf_stubs.h"
#include "motor.h"

static uint64_t expected_servo_mask(void) {
	uint64_t mask = 0;
	for (int i = 0; i < SERVO_COUNT; ++i) {
		servo_output_t output = get_servo_output(i);
		mask |= (1ULL << output.gpio);
	}
	return mask;
}

TEST(angle_to_duty_clamps_at_bounds) {
	uint32_t min = angle_to_duty(0);
	uint32_t max = angle_to_duty(180);
	ASSERT(min <= max);
	ASSERT_EQ(angle_to_duty(180), max);
	ASSERT_EQ(angle_to_duty(200), max);
}

TEST(motor_gpio_init_configures_all_pins) {
	espidf_stubs_reset();
	motor_gpio_init();

	ASSERT(gpio_config_last_call.called);
	ASSERT_EQ(gpio_config_last_call.config.mode, GPIO_MODE_OUTPUT);
	uint64_t expected = (1ULL << IN1_GPIO) | (1ULL << IN2_GPIO) |
	                    (1ULL << IN3_GPIO) | (1ULL << IN4_GPIO) |
	                    expected_servo_mask();
	ASSERT_EQ(gpio_config_last_call.config.pin_bit_mask, expected);
}

TEST(motor_pwm_init_initializes_channels) {
	espidf_stubs_reset();
	motor_pwm_init();

	ASSERT_EQ(ledc_timer_config_last_call.call_count, 2u);
	ASSERT_EQ(ledc_timer_config_last_call.config.timer_num, SERVO_TIMER);
	ASSERT_EQ(ledc_channel_config_last_call.call_count, 2u + SERVO_COUNT);
	ASSERT_EQ(ledc_set_duty_last_call.call_count, (size_t)SERVO_COUNT);
	ASSERT_EQ(ledc_update_duty_last_call.call_count, (size_t)SERVO_COUNT);
	ASSERT_EQ(ledc_channel_config_last_call.config.channel,
	          puppy_servo_outputs[SERVO_COUNT - 1].channel);
}

TEST(servo_set_angle_clamps_and_updates_duty) {
	espidf_stubs_reset();
	servo_set_angle(0, 200);

	ASSERT(ledc_set_duty_last_call.called);
	ASSERT_EQ(ledc_set_duty_last_call.channel, puppy_servo_outputs[0].channel);
	ASSERT_EQ(ledc_set_duty_last_call.duty, angle_to_duty(180));
	ASSERT_EQ(ledc_update_duty_last_call.call_count, 1u);
}

TEST(servo_set_angle_ignores_invalid_servo) {
	espidf_stubs_reset();
	servo_set_angle(SERVO_COUNT, 90);

	ASSERT_EQ(ledc_set_duty_last_call.call_count, 0u);
	ASSERT_EQ(ledc_update_duty_last_call.call_count, 0u);
}
