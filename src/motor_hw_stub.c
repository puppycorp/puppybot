#include "log.h"
#include "motor_hw.h"

#include <math.h>
#include <stdlib.h>

static const char *TAG = "MOTOR_HW";

#define MAX_CHANNELS 16

typedef struct {
	bool valid;
	uint16_t freq_hz;
} pwm_freq_state;

typedef struct {
	bool valid;
	int gpio;
} pwm_pin_state;

typedef struct {
	bool valid;
	uint16_t freq_hz;
	uint16_t pulse_us;
} pwm_pulse_state;

typedef struct {
	bool valid;
	float duty;
} pwm_duty_state;

typedef struct {
	bool valid;
	int in1;
	int in2;
	bool forward;
	bool brake;
} hbridge_state;

static pwm_freq_state g_freq_state[MAX_CHANNELS];
static pwm_pin_state g_pin_state[MAX_CHANNELS];
static pwm_pulse_state g_pulse_state[MAX_CHANNELS];
static pwm_duty_state g_duty_state[MAX_CHANNELS];
static hbridge_state g_hbridge_state;

static const int PULSE_LOG_THRESHOLD_US = 5;
static const float DUTY_LOG_THRESHOLD = 0.01f;

int motor_hw_init(void) {
	log_info(TAG, "Motor hardware stub initialized");
	return 0;
}

void motor_hw_ensure_pwm(uint8_t channel, uint16_t freq_hz) {
	if (channel >= MAX_CHANNELS) {
		return;
	}

	pwm_freq_state *state = &g_freq_state[channel];
	if (state->valid && state->freq_hz == freq_hz) {
		return;
	}

	state->valid = true;
	state->freq_hz = freq_hz;
	log_info(TAG, "Ensure PWM channel %u at %u Hz", channel, freq_hz);
}

void motor_hw_bind_pwm_pin(uint8_t channel, int gpio) {
	if (channel >= MAX_CHANNELS) {
		return;
	}

	pwm_pin_state *state = &g_pin_state[channel];
	if (state->valid && state->gpio == gpio) {
		return;
	}

	state->valid = true;
	state->gpio = gpio;
	log_info(TAG, "Bind PWM channel %u to pin %d", channel, gpio);
}

void motor_hw_set_pwm_pulse_us(uint8_t channel, uint16_t freq_hz,
                               uint16_t pulse_us) {
	if (channel >= MAX_CHANNELS) {
		return;
	}

	pwm_pulse_state *state = &g_pulse_state[channel];
	if (state->valid && state->freq_hz == freq_hz) {
		int delta = abs((int)state->pulse_us - (int)pulse_us);
		if (delta < PULSE_LOG_THRESHOLD_US) {
			state->pulse_us = pulse_us;
			return;
		}
	}

	state->valid = true;
	state->freq_hz = freq_hz;
	state->pulse_us = pulse_us;

	float duty =
	    freq_hz == 0 ? 0.0f : ((float)pulse_us * (float)freq_hz) / 10000.0f;
	log_info(TAG,
	         "Set PWM pulse: channel=%u freq=%uHz pulse=%uus (duty=%.2f%%)",
	         channel, freq_hz, pulse_us, duty);
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
	if (channel >= MAX_CHANNELS) {
		return;
	}

	float duty = clamp_float_01(duty_0_to_1);
	pwm_duty_state *state = &g_duty_state[channel];
	if (state->valid && fabsf(state->duty - duty) < DUTY_LOG_THRESHOLD) {
		state->duty = duty;
		return;
	}

	state->valid = true;
	state->duty = duty;
	log_info(TAG, "Set PWM duty: channel=%u duty=%.2f%%", channel,
	         duty * 100.0f);
}

void motor_hw_configure_hbridge(int in1, int in2, bool forward, bool brake) {
	hbridge_state *state = &g_hbridge_state;
	if (state->valid && state->in1 == in1 && state->in2 == in2 &&
	    state->forward == forward && state->brake == brake) {
		return;
	}

	state->valid = true;
	state->in1 = in1;
	state->in2 = in2;
	state->forward = forward;
	state->brake = brake;

	log_info(TAG, "Configure H-bridge: in1=%d in2=%d direction=%s mode=%s", in1,
	         in2, forward ? "forward" : "reverse", brake ? "brake" : "coast");
}
