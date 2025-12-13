#pragma once

#include <stdbool.h>
#include <stdint.h>

// STServo/SCServo protocol constants (Protocol 1.0 style).
#ifndef SMARTBUS_INST_PING
#define SMARTBUS_INST_PING 0x01
#endif
#ifndef SMARTBUS_INST_READ
#define SMARTBUS_INST_READ 0x02
#endif
#ifndef SMARTBUS_INST_WRITE
#define SMARTBUS_INST_WRITE 0x03
#endif

// Default register addresses for STS/SMS_STS family.
// Override per your servo model if needed.
#ifndef SMARTBUS_ADDR_GOAL_POSITION_L
#define SMARTBUS_ADDR_GOAL_POSITION_L 42
#endif
#ifndef SMARTBUS_ADDR_MODE
#define SMARTBUS_ADDR_MODE 33
#endif
#ifndef SMARTBUS_ADDR_ACC
#define SMARTBUS_ADDR_ACC 41
#endif
#ifndef SMARTBUS_ADDR_PRESENT_POSITION_L
#define SMARTBUS_ADDR_PRESENT_POSITION_L 56
#endif

// Backwards-compatible aliases for older placeholder names.
#ifndef SMARTBUS_CMD_PING
#define SMARTBUS_CMD_PING SMARTBUS_INST_PING
#endif
#ifndef SMARTBUS_CMD_READ_POS
#define SMARTBUS_CMD_READ_POS SMARTBUS_ADDR_PRESENT_POSITION_L
#endif

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

// Sets the servo mode register (typically 0=positional, 1=wheel).
void motor_hw_smartbus_set_mode(uint8_t uart_port, uint8_t servo_id,
                                uint8_t mode);

// Sets wheel speed for smart servos (requires wheel mode). `speed_raw` uses the
// STServo "sign bit" convention (bit 15 indicates negative direction).
void motor_hw_smartbus_set_wheel_speed(uint8_t uart_port, uint8_t servo_id,
                                       int16_t speed_raw, uint8_t acc);
// Reads raw position units from smart servo over smartbus.
// Returns 0 on success, negative on error.
int motor_hw_smartbus_read_position(uint8_t uart_port, uint8_t servo_id,
                                    uint16_t *pos_raw_out);

// Pings a smart servo ID on the bus. Returns 0 if a valid reply is received.
int motor_hw_smartbus_ping(uint8_t uart_port, uint8_t servo_id, int timeout_ms);
