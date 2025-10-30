#include "log.h"
#include "motor_hw.h"

static const char *TAG = "MOTOR_HW";

int motor_hw_init(void) {
	log_info(TAG, "Motor hardware stub initialized");
	return 0;
}

void motor_hw_ensure_pwm(uint8_t channel, uint16_t freq_hz) {
	log_info(TAG, "Ensure PWM channel %u at %u Hz", channel, freq_hz);
}

void motor_hw_bind_pwm_pin(uint8_t channel, int gpio) {
	log_info(TAG, "Bind PWM channel %u to pin %d", channel, gpio);
}

void motor_hw_set_pwm_pulse_us(uint8_t channel, uint16_t freq_hz,
                               uint16_t pulse_us) {
	log_info(
	    TAG, "Set PWM pulse: channel=%u freq=%uHz pulse=%uus (duty=%.2f%%)",
	    channel, freq_hz, pulse_us,
	    freq_hz == 0 ? 0.0f : ((float)pulse_us * (float)freq_hz) / 10000.0f);
}

static float clamp_float_01(float value) {
	if (value < 0.0f) {
		return 0.0f;
	}
	if (value > 1.0f) {
		return 1.0f;
	}
	return value;
}

void motor_hw_set_pwm_duty(uint8_t channel, float duty_0_to_1) {
	float duty = clamp_float_01(duty_0_to_1);
	log_info(TAG, "Set PWM duty: channel=%u duty=%.2f%%", channel,
	         duty * 100.0f);
}

void motor_hw_configure_hbridge(int in1, int in2, bool forward, bool brake) {
	log_info(TAG, "Configure H-bridge: in1=%d in2=%d direction=%s mode=%s", in1,
	         in2, forward ? "forward" : "reverse", brake ? "brake" : "coast");
}
