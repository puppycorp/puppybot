#pragma once

#include <stdbool.h>
#include <stdint.h>

// Motor hardware abstraction layer
int motor_hw_init(void);
void motor_hw_ensure_pwm(uint8_t channel, uint16_t freq_hz);
void motor_hw_bind_pwm_pin(uint8_t channel, int gpio);
void motor_hw_set_pwm_pulse_us(uint8_t channel, uint16_t freq_hz,
                               uint16_t pulse_us);
void motor_hw_set_pwm_duty(uint8_t channel, float duty_0_to_1);
void motor_hw_configure_hbridge(int in1, int in2, bool forward, bool brake);
uint32_t motor_hw_now_ms(void);
