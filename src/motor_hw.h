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
int motor_hw_configure_smartbus(uint8_t uart_port, int tx_pin, int rx_pin,
                                uint32_t baud_rate);
void motor_hw_smartbus_move(uint8_t uart_port, uint8_t servo_id,
                            uint16_t angle_x10, uint16_t duration_ms);
