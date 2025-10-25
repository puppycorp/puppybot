#include "motor_hw.h"

#ifdef ESP_PLATFORM
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_timer.h"
#else
#include <sys/time.h>

#include "espidf_stubs.h"
#endif

#include <math.h>

static int default_init(void) { return 0; }

static inline uint32_t clamp_u32(uint32_t value, uint32_t max) {
	return value > max ? max : value;
}

static inline uint32_t pwm_duty_from_us(uint16_t freq_hz, uint16_t pulse_us) {
	if (freq_hz == 0)
		return 0;
	uint32_t period_us = 1000000UL / (uint32_t)freq_hz;
	if (period_us == 0)
		return 0;
	uint64_t duty = (uint64_t)pulse_us * ((1u << 16) - 1);
	duty /= period_us;
	return clamp_u32((uint32_t)duty, (1u << 16) - 1);
}

static inline uint32_t pwm_duty_from_ratio(float duty) {
	if (duty < 0.0f)
		duty = 0.0f;
	if (duty > 1.0f)
		duty = 1.0f;
	return (uint32_t)lroundf(duty * ((1u << 16) - 1));
}

static ledc_timer_t timer_for_channel(uint8_t ch) {
	return (ledc_timer_t)(LEDC_TIMER_0 + (ch / 4));
}

static void default_ensure_pwm(uint8_t channel, uint16_t freq_hz) {
	ledc_timer_config_t tcfg = {
	    .speed_mode = LEDC_LOW_SPEED_MODE,
	    .duty_resolution = LEDC_TIMER_16_BIT,
	    .timer_num = timer_for_channel(channel),
	    .freq_hz = freq_hz,
	    .clk_cfg = LEDC_AUTO_CLK,
	};
	ledc_timer_config(&tcfg);

	ledc_channel_config_t ccfg = {
	    .gpio_num = -1,
	    .speed_mode = LEDC_LOW_SPEED_MODE,
	    .channel = (ledc_channel_t)channel,
	    .timer_sel = tcfg.timer_num,
	    .duty = 0,
	    .hpoint = 0,
	};
	ledc_channel_config(&ccfg);
}

static void default_bind_pwm_pin(uint8_t channel, int gpio) {
	ledc_channel_config_t ccfg = {
	    .gpio_num = gpio,
	    .speed_mode = LEDC_LOW_SPEED_MODE,
	    .channel = (ledc_channel_t)channel,
	    .timer_sel = timer_for_channel(channel),
	    .duty = 0,
	    .hpoint = 0,
	};
	ledc_channel_config(&ccfg);
}

static void default_set_pwm_pulse_us(uint8_t channel, uint16_t freq_hz,
                                     uint16_t pulse_us) {
	uint32_t duty = pwm_duty_from_us(freq_hz, pulse_us);
	ledc_set_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)channel, duty);
	ledc_update_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)channel);
}

static void default_set_pwm_duty(uint8_t channel, float duty_ratio) {
	uint32_t duty = pwm_duty_from_ratio(duty_ratio);
	ledc_set_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)channel, duty);
	ledc_update_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)channel);
}

static void default_configure_hbridge(int in1, int in2, bool forward,
                                      bool brake) {
	if (in1 < 0 || in2 < 0)
		return;
	gpio_config_t cfg = {
	    .pin_bit_mask = (1ULL << in1) | (1ULL << in2),
	    .mode = GPIO_MODE_OUTPUT,
	    .pull_up_en = GPIO_PULLUP_DISABLE,
	    .pull_down_en = GPIO_PULLDOWN_DISABLE,
	    .intr_type = GPIO_INTR_DISABLE,
	};
	gpio_config(&cfg);
	if (brake) {
		int level = forward ? 1 : 0;
		gpio_set_level((gpio_num_t)in1, level);
		gpio_set_level((gpio_num_t)in2, level);
	} else {
		gpio_set_level((gpio_num_t)in1, forward ? 1 : 0);
		gpio_set_level((gpio_num_t)in2, forward ? 0 : 1);
	}
}

static uint32_t default_now_ms(void) {
#ifdef ESP_PLATFORM
	return (uint32_t)(esp_timer_get_time() / 1000);
#else
	struct timeval tv;
	gettimeofday(&tv, NULL);
	uint64_t ms = (uint64_t)tv.tv_sec * 1000ULL + tv.tv_usec / 1000ULL;
	return (uint32_t)ms;
#endif
}

static const motor_hw_ops_t g_default_ops = {
    .init = default_init,
    .ensure_pwm = default_ensure_pwm,
    .bind_pwm_pin = default_bind_pwm_pin,
    .set_pwm_pulse_us = default_set_pwm_pulse_us,
    .set_pwm_duty = default_set_pwm_duty,
    .configure_hbridge = default_configure_hbridge,
    .now_ms = default_now_ms,
};

const motor_hw_ops_t *motor_hw_default_ops(void) { return &g_default_ops; }
