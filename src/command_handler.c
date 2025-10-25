#include "command_handler.h"
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#define TAG "COMMAND"
#define MAX_SERVOS 8

// Internal state structures
typedef struct {
	CommandTimerHandle timer;
	uint16_t restore_angle;
	bool active;
} ServoTimeoutState;

// Module-level state
static const CommandOps *g_ops = NULL;
static CommandTimerHandle g_safety_timer = NULL;
static ServoTimeoutState g_servo_timeouts[MAX_SERVOS];
static uint16_t g_servo_current_angle[MAX_SERVOS];

// Forward declarations
static void safety_timer_callback(void *arg);
static void servo_timeout_callback(void *arg);
static uint8_t speed_to_duty(int speed);
static void cancel_servo_timeout(uint8_t servo_id);

// Timer callbacks
static void safety_timer_callback(void *arg) {
	(void)arg;
	if (g_ops && g_ops->log_warning) {
		g_ops->log_warning(TAG, "Safety timeout: stopping all motors");
	}
	if (g_ops) {
		if (g_ops->motor_a_stop)
			g_ops->motor_a_stop();
		if (g_ops->motor_b_stop)
			g_ops->motor_b_stop();
	}
}

static void servo_timeout_callback(void *arg) {
	uint32_t servo_id = (uint32_t)(uintptr_t)arg;
	if (servo_id >= MAX_SERVOS) {
		return;
	}

	uint32_t servo_count = g_ops && g_ops->servo_count ? g_ops->servo_count() : 0;
	if (servo_id >= servo_count) {
		return;
	}

	ServoTimeoutState *state = &g_servo_timeouts[servo_id];
	if (g_ops && g_ops->log_info) {
		g_ops->log_info(TAG, "Servo %lu timeout -> restoring to %d",
		                (unsigned long)servo_id, state->restore_angle);
	}

	if (g_ops && g_ops->servo_set_angle) {
		g_ops->servo_set_angle((uint8_t)servo_id, state->restore_angle);
	}
	g_servo_current_angle[servo_id] = state->restore_angle;
	state->active = false;
}

static void cancel_servo_timeout(uint8_t servo_id) {
	if (servo_id >= MAX_SERVOS) {
		return;
	}

	uint32_t servo_count = g_ops && g_ops->servo_count ? g_ops->servo_count() : 0;
	if (servo_id >= servo_count) {
		return;
	}

	ServoTimeoutState *state = &g_servo_timeouts[servo_id];
	if (state->timer == NULL || !g_ops || !g_ops->timer_stop) {
		return;
	}

	int stop_result = g_ops->timer_stop(state->timer);
	// ESP_OK = 0, ESP_ERR_INVALID_STATE is typically != 0
	// We ignore the error if it's already stopped
	if (stop_result != 0 && g_ops->log_warning) {
		g_ops->log_warning(TAG, "Failed to stop servo timeout %u", servo_id);
	}
	state->active = false;
}

static uint8_t speed_to_duty(int speed) {
	int magnitude = abs(speed);
	if (magnitude > 127) {
		magnitude = 127;
	}
	// Map 0..127 -> 0..255 for LEDC 8-bit duty cycle
	return (uint8_t)((magnitude * 255) / 127);
}

void command_handler_init(const CommandOps *ops) {
	if (!ops) {
		return;
	}

	g_ops = ops;

	// Create safety timer
	if (g_ops->timer_create) {
		g_safety_timer =
		    g_ops->timer_create(safety_timer_callback, NULL, "safety_timer");
		if (g_safety_timer == NULL && g_ops->log_error) {
			g_ops->log_error(TAG, "Failed to create safety timer");
		} else if (g_ops->log_info) {
			g_ops->log_info(TAG, "Safety timer created successfully");
		}
	}

	// Initialize servo timeout timers
	uint32_t servo_count = g_ops->servo_count ? g_ops->servo_count() : 0;
	for (uint8_t servo = 0; servo < servo_count && servo < MAX_SERVOS; ++servo) {
		ServoTimeoutState *state = &g_servo_timeouts[servo];

		uint32_t boot_angle =
		    g_ops->servo_boot_angle ? g_ops->servo_boot_angle(servo) : 90;
		g_servo_current_angle[servo] = (uint16_t)boot_angle;
		state->restore_angle = (uint16_t)boot_angle;
		state->active = false;

		if (g_ops->timer_create) {
			state->timer = g_ops->timer_create(servo_timeout_callback,
			                                    (void *)(uintptr_t)servo, NULL);
			if (state->timer == NULL && g_ops->log_error) {
				g_ops->log_error(TAG, "Failed to create servo timeout timer %u",
				                 servo);
			}
		} else {
			state->timer = NULL;
		}
	}
}

void command_handler_handle(CommandPacket *cmd, void *client) {
	if (!cmd || !g_ops) {
		return;
	}

	switch (cmd->cmd_type) {
	case CMD_PING:
		if (g_ops->log_info) {
			g_ops->log_info(TAG, "Ping command received");
		}
		if (client && g_ops->websocket_send_pong) {
			g_ops->websocket_send_pong(client);
		}
		break;

	case CMD_DRIVE_MOTOR:
		if (g_ops->log_info) {
			g_ops->log_info(TAG, "drive motor %d with speed %d",
			                cmd->cmd.drive_motor.motor_id,
			                cmd->cmd.drive_motor.speed);
		}

		// Reset the safety timer
		if (g_safety_timer && g_ops->timer_stop && g_ops->timer_start_once) {
			g_ops->timer_stop(g_safety_timer);
			g_ops->timer_start_once(g_safety_timer, 1000000); // 1 second timeout
		}

		if (cmd->cmd.drive_motor.motor_type == SERVO_MOTOR) {
			uint8_t servo_id = (uint8_t)cmd->cmd.drive_motor.motor_id;
			uint32_t servo_count =
			    g_ops->servo_count ? g_ops->servo_count() : 0;

			if (servo_id >= servo_count) {
				if (g_ops->log_error) {
					g_ops->log_error(TAG, "Invalid servo ID %u", servo_id);
				}
				break;
			}

			cancel_servo_timeout(servo_id);

			int angle = cmd->cmd.drive_motor.angle;
			if (angle < 0)
				angle = 0;
			if (angle > 180)
				angle = 180;

			if (g_ops->servo_set_angle) {
				g_ops->servo_set_angle(servo_id, (uint32_t)angle);
			}
			g_servo_current_angle[servo_id] = (uint16_t)angle;

		} else if (cmd->cmd.drive_motor.motor_id == 1) {
			// Motor A
			if (cmd->cmd.drive_motor.speed == 0) {
				if (g_ops->motor_a_stop)
					g_ops->motor_a_stop();
				break;
			}
			uint8_t duty = speed_to_duty(cmd->cmd.drive_motor.speed);
			if (cmd->cmd.drive_motor.speed > 0) {
				if (g_ops->motor_a_forward)
					g_ops->motor_a_forward(duty);
			} else {
				if (g_ops->motor_a_backward)
					g_ops->motor_a_backward(duty);
			}

		} else if (cmd->cmd.drive_motor.motor_id == 2) {
			// Motor B
			if (cmd->cmd.drive_motor.speed == 0) {
				if (g_ops->motor_b_stop)
					g_ops->motor_b_stop();
				break;
			}
			uint8_t duty = speed_to_duty(cmd->cmd.drive_motor.speed);
			if (cmd->cmd.drive_motor.speed > 0) {
				if (g_ops->motor_b_forward)
					g_ops->motor_b_forward(duty);
			} else {
				if (g_ops->motor_b_backward)
					g_ops->motor_b_backward(duty);
			}

		} else {
			if (g_ops->log_error) {
				g_ops->log_error(TAG, "Invalid motor ID");
			}
		}
		break;

	case CMD_STOP_MOTOR:
		if (g_ops->log_info) {
			g_ops->log_info(TAG, "stop motor %d", cmd->cmd.stop_motor.motor_id);
		}
		if (cmd->cmd.stop_motor.motor_id == 1) {
			if (g_ops->motor_a_stop)
				g_ops->motor_a_stop();
		} else if (cmd->cmd.stop_motor.motor_id == 2) {
			if (g_ops->motor_b_stop)
				g_ops->motor_b_stop();
		} else {
			if (g_ops->log_error) {
				g_ops->log_error(TAG, "Invalid motor ID");
			}
		}
		break;

	case CMD_STOP_ALL_MOTORS:
		if (g_ops->log_info) {
			g_ops->log_info(TAG, "Stop all motors command received");
		}
		if (g_ops->motor_a_stop)
			g_ops->motor_a_stop();
		if (g_ops->motor_b_stop)
			g_ops->motor_b_stop();

		if (g_safety_timer && g_ops->timer_stop) {
			g_ops->timer_stop(g_safety_timer);
		}

		uint32_t servo_count = g_ops->servo_count ? g_ops->servo_count() : 0;
		for (uint8_t servo = 0; servo < servo_count && servo < MAX_SERVOS;
		     ++servo) {
			cancel_servo_timeout(servo);
			uint32_t boot_angle =
			    g_ops->servo_boot_angle ? g_ops->servo_boot_angle(servo) : 90;
			if (g_ops->servo_set_angle) {
				g_ops->servo_set_angle(servo, boot_angle);
			}
			g_servo_current_angle[servo] = (uint16_t)boot_angle;
		}
		break;

	case CMD_TURN_SERVO: {
		uint8_t servo_id = (uint8_t)cmd->cmd.turn_servo.servo_id;
		int angle = cmd->cmd.turn_servo.angle;
		int duration_ms = cmd->cmd.turn_servo.duration_ms;

		uint32_t servo_count = g_ops->servo_count ? g_ops->servo_count() : 0;
		if (servo_id >= servo_count) {
			if (g_ops->log_error) {
				g_ops->log_error(TAG, "Invalid servo ID %u", servo_id);
			}
			break;
		}

		if (angle < 0)
			angle = 0;
		if (angle > 180)
			angle = 180;
		if (duration_ms < 0)
			duration_ms = 0;

		uint16_t previous_angle = g_servo_current_angle[servo_id];
		cancel_servo_timeout(servo_id);

		if (g_ops->log_info) {
			g_ops->log_info(TAG, "turn servo %u -> %d (timeout %d ms)", servo_id,
			                angle, duration_ms);
		}

		if (g_ops->servo_set_angle) {
			g_ops->servo_set_angle(servo_id, (uint32_t)angle);
		}
		g_servo_current_angle[servo_id] = (uint16_t)angle;

		if (duration_ms > 0) {
			ServoTimeoutState *state = &g_servo_timeouts[servo_id];
			if (state->timer == NULL) {
				if (g_ops->log_warning) {
					g_ops->log_warning(TAG, "No timer available for servo %u timeout",
					                   servo_id);
				}
				break;
			}

			state->restore_angle = previous_angle;
			state->active = true;
			int64_t timeout_us = (int64_t)duration_ms * 1000;

			if (g_ops->timer_start_once) {
				int timer_result =
				    g_ops->timer_start_once(state->timer, timeout_us);
				if (timer_result != 0) {
					if (g_ops->log_warning) {
						g_ops->log_warning(TAG, "Failed to start servo timeout %u",
						                   servo_id);
					}
					state->active = false;
				}
			}
		}
		break;
	}
	}
}
