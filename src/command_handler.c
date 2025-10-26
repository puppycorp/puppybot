#include "command_handler.h"
#include "comm.h"
#include "log.h"
#include "motor_runtime.h"
#include "motor_slots.h"
#include "timer.h"
#include <inttypes.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#define TAG "COMMAND"
#define MAX_SERVOS 8

// Internal state structures
typedef struct {
	timer_t timer;
	uint16_t restore_angle;
	bool active;
} ServoTimeoutState;

// Module-level state
static timer_t g_safety_timer = NULL;
static ServoTimeoutState g_servo_timeouts[MAX_SERVOS];
static uint16_t g_servo_current_angle[MAX_SERVOS];

static inline uint32_t servo_slot_count(void) {
	int count = motor_slots_servo_count();
	if (count < 0)
		return 0;
	if (count > MAX_SERVOS)
		count = MAX_SERVOS;
	return (uint32_t)count;
}

static int servo_slot_from_node(uint32_t node_id) {
	int count = motor_slots_servo_count();
	for (int slot = 0; slot < count && slot < MAX_SERVOS; ++slot) {
		motor_rt_t *m = motor_slots_servo(slot);
		if (m && m->node_id == node_id)
			return slot;
	}
	return -1;
}

static motor_rt_t *find_motor(uint32_t node_id) {
	motor_rt_t *m = NULL;
	if (motor_registry_find(node_id, &m) == 0)
		return m;
	return NULL;
}

static float normalize_speed(int speed) {
	if (speed > 127)
		speed = 127;
	if (speed < -127)
		speed = -127;
	return (float)speed / 127.0f;
}

// Forward declarations
static void servo_timeout_callback(void *arg);
static void safety_timer_callback(void *arg);
static void cancel_servo_timeout(uint8_t servo_id);

static void ensure_servo_timer(uint8_t slot) {
	if (slot >= MAX_SERVOS)
		return;
	ServoTimeoutState *state = &g_servo_timeouts[slot];
	if (state->timer)
		return;
	state->timer =
	    timer_create(servo_timeout_callback, (void *)(uintptr_t)slot, NULL);
	if (!state->timer) {
		log_error(TAG, "Failed to create servo timeout timer %u", slot);
	}
}

static void stop_all_drive_motors(void) {
	int drive_count = motor_slots_drive_count();
	for (int idx = 0; idx < drive_count; ++idx) {
		motor_rt_t *m = motor_slots_drive(idx);
		if (m)
			motor_stop(m->node_id);
	}
}

// Timer callbacks
static void safety_timer_callback(void *arg) {
	(void)arg;
	log_warn(TAG, "Safety timeout: stopping all motors");
	stop_all_drive_motors();
}

static void servo_timeout_callback(void *arg) {
	uint32_t servo_id = (uint32_t)(uintptr_t)arg;
	if (servo_id >= MAX_SERVOS) {
		return;
	}

	uint32_t count = servo_slot_count();
	if (servo_id >= count) {
		return;
	}

	ServoTimeoutState *state = &g_servo_timeouts[servo_id];
	motor_rt_t *motor = motor_slots_servo((int)servo_id);
	if (!motor) {
		return;
	}

	log_info(TAG, "Servo %lu timeout -> restoring to %d",
	         (unsigned long)servo_id, state->restore_angle);

	motor_set_angle(motor->node_id, (float)state->restore_angle);
	g_servo_current_angle[servo_id] = state->restore_angle;
	state->active = false;
}

static void cancel_servo_timeout(uint8_t servo_id) {
	if (servo_id >= MAX_SERVOS) {
		return;
	}

	uint32_t count = servo_slot_count();
	if (servo_id >= count) {
		return;
	}

	ServoTimeoutState *state = &g_servo_timeouts[servo_id];
	if (state->timer == NULL) {
		return;
	}

	int stop_result = timer_stop(state->timer);
	if (stop_result != 0) {
		log_warn(TAG, "Failed to stop servo timeout %u", servo_id);
	}
	state->active = false;
}

void command_handler_init(void) {
	// Create safety timer
	g_safety_timer = timer_create(safety_timer_callback, NULL, "safety_timer");
	if (g_safety_timer == NULL) {
		log_error(TAG, "Failed to create safety timer");
	} else {
		log_info(TAG, "Safety timer created successfully");
	}

	// Initialize servo timeout timers
	command_handler_reload_motor_config();
}

void command_handler_reload_motor_config(void) {
	uint32_t count = servo_slot_count();
	for (uint8_t slot = 0; slot < count && slot < MAX_SERVOS; ++slot) {
		ensure_servo_timer(slot);
		cancel_servo_timeout(slot);
		float boot = motor_slots_servo_boot_angle((int)slot);
		if (boot < 0.0f)
			boot = 0.0f;
		if (boot > 180.0f)
			boot = 180.0f;
		uint16_t boot_u16 = (uint16_t)boot;
		g_servo_current_angle[slot] = boot_u16;
		ServoTimeoutState *state = &g_servo_timeouts[slot];
		state->restore_angle = boot_u16;
		state->active = false;
	}

	for (uint8_t slot = (uint8_t)count; slot < MAX_SERVOS; ++slot) {
		ServoTimeoutState *state = &g_servo_timeouts[slot];
		if (state->timer) {
			timer_stop(state->timer);
		}
		state->active = false;
		g_servo_current_angle[slot] = 90;
	}
}

void command_handler_handle(CommandPacket *cmd, void *client) {
	if (!cmd) {
		return;
	}

	switch (cmd->cmd_type) {
	case CMD_PING:
		log_info(TAG, "Ping command received");
		if (client) {
			send_pong(client);
		}
		break;

	case CMD_DRIVE_MOTOR: {
		log_info(TAG, "drive motor %d with speed %d",
		         cmd->cmd.drive_motor.motor_id, cmd->cmd.drive_motor.speed);

		// Reset the safety timer
		if (g_safety_timer) {
			timer_stop(g_safety_timer);
			timer_start_once(g_safety_timer, 1000000); // 1 second timeout
		}

		uint32_t node_id = (uint32_t)cmd->cmd.drive_motor.motor_id;
		motor_rt_t *motor = find_motor(node_id);
		if (!motor) {
			log_error(TAG, "Unknown motor node %" PRIu32, node_id);
			break;
		}

		if (motor->type_id == MOTOR_TYPE_ANGLE) {
			int slot = servo_slot_from_node(node_id);
			if (slot < 0) {
				log_error(TAG,
				          "Servo node %" PRIu32 " not mapped to a servo slot",
				          node_id);
				break;
			}
			cancel_servo_timeout((uint8_t)slot);
			int angle = cmd->cmd.drive_motor.angle;
			if (angle < 0)
				angle = 0;
			if (angle > 180)
				angle = 180;
			motor_set_angle(node_id, (float)angle);
			g_servo_current_angle[slot] = (uint16_t)angle;
			break;
		}

		float speed = normalize_speed(cmd->cmd.drive_motor.speed);
		if (cmd->cmd.drive_motor.speed == 0) {
			motor_stop(node_id);
			break;
		}
		if (motor_set_speed(node_id, speed) != 0) {
			log_error(TAG, "Failed to set speed for motor %" PRIu32, node_id);
		}
		break;
	}

	case CMD_STOP_MOTOR: {
		log_info(TAG, "stop motor %d", cmd->cmd.stop_motor.motor_id);
		uint32_t node_id = (uint32_t)cmd->cmd.stop_motor.motor_id;
		motor_rt_t *motor = find_motor(node_id);
		if (!motor) {
			log_error(TAG, "Unknown motor node %" PRIu32, node_id);
			break;
		}
		if (motor->type_id == MOTOR_TYPE_ANGLE) {
			int slot = servo_slot_from_node(node_id);
			if (slot >= 0) {
				cancel_servo_timeout((uint8_t)slot);
				// Keep servo at its current angle; nothing further required.
			}
		} else {
			motor_stop(node_id);
		}
		break;
	}

	case CMD_STOP_ALL_MOTORS:
		log_info(TAG, "Stop all motors command received");
		stop_all_drive_motors();

		if (g_safety_timer) {
			timer_stop(g_safety_timer);
		}

		uint32_t count = servo_slot_count();
		for (uint8_t slot = 0; slot < count && slot < MAX_SERVOS; ++slot) {
			cancel_servo_timeout(slot);
			float boot = motor_slots_servo_boot_angle((int)slot);
			if (boot < 0.0f)
				boot = 0.0f;
			if (boot > 180.0f)
				boot = 180.0f;
			motor_rt_t *motor = motor_slots_servo(slot);
			if (motor)
				motor_set_angle(motor->node_id, boot);
			g_servo_current_angle[slot] = (uint16_t)boot;
		}
		break;
	}
}
