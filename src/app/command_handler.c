#include "command_handler.h"
#include "arm_ik.h"
#include "http.h"
#include "platform.h"
#include "log.h"
#include "motor_config.h"
#include "motor_hw.h"
#include "motor_runtime.h"
#include "motor_slots.h"
#include "timer.h"
#include "puppyarm/puppyarm.h"
#include <inttypes.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define TAG "COMMAND"
#define MAX_SERVOS 8

// Internal state structures
typedef struct {
	puppy_timer_t timer;
	uint16_t restore_angle;
	bool active;
} ServoTimeoutState;

// Module-level state
static puppy_timer_t g_safety_timer = NULL;
static ServoTimeoutState g_servo_timeouts[MAX_SERVOS];
static uint16_t g_servo_current_angle[MAX_SERVOS];

static int clamp_motor_angle_deg(const motor_rt_t *motor, int angle_deg) {
	if (!motor)
		return angle_deg;

	if (motor->type_id == MOTOR_TYPE_SMART && motor->smart_limit_raw) {
		uint16_t raw = motor_smart_deg_to_raw(motor, (float)angle_deg);
		uint16_t min_raw = motor->smart_min_raw;
		uint16_t max_raw = motor->smart_max_raw;
		if (min_raw > max_raw) {
			uint16_t tmp = min_raw;
			min_raw = max_raw;
			max_raw = tmp;
		}
		if (raw < min_raw)
			raw = min_raw;
		if (raw > max_raw)
			raw = max_raw;
		return (int)lroundf(motor_smart_raw_to_deg(motor, raw));
	}

	int32_t min_x10 = motor->deg_min_x10;
	int32_t max_x10 = motor->deg_max_x10;
	if (min_x10 > max_x10) {
		int32_t tmp = min_x10;
		min_x10 = max_x10;
		max_x10 = tmp;
	}

	int32_t angle_x10 = (int32_t)angle_deg * 10;
	if (angle_x10 < min_x10)
		angle_x10 = min_x10;
	if (angle_x10 > max_x10)
		angle_x10 = max_x10;

	if (angle_x10 >= 0)
		return (int)((angle_x10 + 5) / 10);
	return (int)((angle_x10 - 5) / 10);
}

static float wrap_angle_deg(float deg) {
	float wrapped = fmodf(deg, 360.0f);
	if (wrapped < 0.0f)
		wrapped += 360.0f;
	return wrapped;
}

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

static float deg_to_rad(float deg) { return deg * (PUPPYARM_PI / 180.0f); }

static uint16_t clamp_arm_speed(uint16_t speed) {
	return speed > 1000 ? 1000 : speed;
}

static float arm_table_z_to_shoulder_z(float z_mm) {
	const puppyarm_controller_t *ctrl = puppyarm_controller();
	if (!ctrl)
		return z_mm;
	return z_mm - ctrl->profile.z_origin_mm;
}

static void log_arm_result(const char *name, int rc) {
	if (rc != 0)
		log_warn(TAG, "%s failed (%d)", name, rc);
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
	state->timer = puppy_timer_create(servo_timeout_callback,
	                                  (void *)(uintptr_t)slot, NULL);
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

static void send_smartbus_scan_result(uint8_t uart_port, uint8_t start_id,
                                      uint8_t end_id, const uint8_t *ids,
                                      uint8_t count) {
	uint8_t buf[2 + 1 + 1 + 1 + 1 + 1 + 64];
	if (count > 64)
		count = 64;
	size_t off = 0;
	buf[off++] = (uint8_t)(PUPPY_PROTOCOL_VERSION & 0xff);
	buf[off++] = (uint8_t)((PUPPY_PROTOCOL_VERSION >> 8) & 0xff);
	buf[off++] = MSG_TO_SRV_SMARTBUS_SCAN_RESULT;
	buf[off++] = uart_port;
	buf[off++] = start_id;
	buf[off++] = end_id;
	buf[off++] = count;
	for (uint8_t i = 0; i < count; ++i)
		buf[off++] = ids[i];
	(void)ws_client_send(buf, off);
}

static void send_smartbus_set_id_result(uint8_t uart_port, uint8_t old_id,
                                        uint8_t new_id, uint8_t status) {
	uint8_t buf[2 + 1 + 1 + 1 + 1 + 1];
	size_t off = 0;
	buf[off++] = (uint8_t)(PUPPY_PROTOCOL_VERSION & 0xff);
	buf[off++] = (uint8_t)((PUPPY_PROTOCOL_VERSION >> 8) & 0xff);
	buf[off++] = MSG_TO_SRV_SMARTBUS_SET_ID_RESULT;
	buf[off++] = uart_port;
	buf[off++] = old_id;
	buf[off++] = new_id;
	buf[off++] = status;
	(void)ws_client_send(buf, off);
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

	int stop_result = puppy_timer_stop(state->timer);
	if (stop_result != 0) {
		log_warn(TAG, "Failed to stop servo timeout %u", servo_id);
	}
	state->active = false;
}

void command_handler_init(void) {
	// Create safety timer
	g_safety_timer =
	    puppy_timer_create(safety_timer_callback, NULL, "safety_timer");
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
			puppy_timer_stop(state->timer);
		}
		state->active = false;
		g_servo_current_angle[slot] = 90;
	}
}

void command_handler_handle(CommandPacket *cmd) {
	if (!cmd)
		return;

	switch (cmd->cmd_type) {
	case CMD_PING:
		log_info(TAG, "Ping command received");
		break;
	case CMD_APPLY_CONFIG: {
		log_info(TAG, "CMD_APPLY_CONFIG");
		if (!cmd->cmd.apply_config.data || cmd->cmd.apply_config.length == 0) {
			log_warn(TAG, "Received empty PBCL config payload");
			break;
		}
		int rc = motor_config_apply_blob(cmd->cmd.apply_config.data,
		                                 cmd->cmd.apply_config.length);
		if (rc != 0) {
			log_error(TAG, "motor_config_apply_blob failed (%d)", rc);
		} else {
			log_info(TAG, "Motor configuration applied (%u bytes)",
			         (unsigned)cmd->cmd.apply_config.length);
			if (motor_config_persist_active() != 0) {
				log_warn(TAG, "Failed to persist motor config");
			}
			// Reload servo timeout state after config changes
			command_handler_reload_motor_config();
		}
		break;
	}
	case CMD_DRIVE_MOTOR: {
		log_info(TAG, "CMD_DRIVE_MOTOR motor %d with speed %d",
		         cmd->cmd.drive_motor.motor_id, cmd->cmd.drive_motor.speed);

		// Reset the safety timer
		/*if (g_safety_timer) {
		    puppy_timer_stop(g_safety_timer);
		    puppy_timer_start_once(g_safety_timer, 1000000); // 1 second timeout
		}*/

		uint32_t node_id = (uint32_t)cmd->cmd.drive_motor.motor_id;
		motor_rt_t *motor = find_motor(node_id);
		if (!motor) {
			log_error(TAG, "Unknown motor node %" PRIu32, node_id);
			break;
		}

		if (motor->type_id == MOTOR_TYPE_SMART &&
		    cmd->cmd.drive_motor.motor_type == DC_MOTOR) {
			float speed = normalize_speed(cmd->cmd.drive_motor.speed);
			if (cmd->cmd.drive_motor.speed == 0) {
				// Keep smart servos in wheel mode for an explicit stop.
				motor_set_smart_speed(node_id, 0.0f);
			} else if (motor_set_smart_speed(node_id, speed) != 0) {
				log_error(TAG, "Failed to set smart speed for motor %" PRIu32,
				          node_id);
			}
			break;
		}

		if (motor->type_id == MOTOR_TYPE_ANGLE ||
		    motor->type_id == MOTOR_TYPE_SMART) {
			int slot = servo_slot_from_node(node_id);
			if (slot < 0) {
				log_error(TAG,
				          "Servo node %" PRIu32 " not mapped to a servo slot",
				          node_id);
				break;
			}
			cancel_servo_timeout((uint8_t)slot);
			int angle = cmd->cmd.drive_motor.angle;
			angle = clamp_motor_angle_deg(motor, angle);
			uint16_t duration_ms = 0;
			if (cmd->cmd.drive_motor.steps > 0)
				duration_ms = (uint16_t)cmd->cmd.drive_motor.steps;
			if (motor->type_id == MOTOR_TYPE_SMART) {
				motor_set_smart_angle(node_id, (float)angle, duration_ms);
			} else {
				motor_set_angle(node_id, (float)angle);
			}
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
	case CMD_ARM_MOVE: {
		const arm_config_t *cfg = arm_config_get();
		if (!cfg || !cfg->configured ||
		    cfg->joint_count != ARM_IK_MAX_JOINTS) {
			log_warn(TAG, "Arm config not ready for IK move");
			break;
		}

		float angles[ARM_IK_MAX_JOINTS] = {0};
		int rc = arm_ik_solve(cfg, cmd->cmd.arm_move.x, cmd->cmd.arm_move.y,
		                      cmd->cmd.arm_move.z,
		                      cmd->cmd.arm_move.elbow_up != 0, angles);
		if (rc != 0) {
			log_warn(TAG, "arm_ik_solve failed (%d)", rc);
			break;
		}

		uint16_t duration_ms = cmd->cmd.arm_move.duration_ms;
		for (int i = 0; i < ARM_IK_MAX_JOINTS; ++i) {
			const arm_joint_map_t *joint = &cfg->joints[i];
			if (joint->motor_id == 0)
				continue;
			motor_rt_t *motor = find_motor(joint->motor_id);
			if (!motor) {
				log_warn(TAG, "Unknown arm motor %" PRIu32, joint->motor_id);
				continue;
			}
			if (motor->type_id != MOTOR_TYPE_ANGLE &&
			    motor->type_id != MOTOR_TYPE_SMART) {
				log_warn(TAG, "Arm motor %" PRIu32 " is not a servo",
				         joint->motor_id);
				continue;
			}

			int slot = servo_slot_from_node(joint->motor_id);
			if (slot >= 0) {
				cancel_servo_timeout((uint8_t)slot);
			}

			float servo_deg =
			    wrap_angle_deg((float)joint->sign * angles[i] + joint->offset_deg);
			int angle = (int)lroundf(servo_deg);
			angle = clamp_motor_angle_deg(motor, angle);
			if (motor->type_id == MOTOR_TYPE_SMART) {
				motor_set_smart_angle(joint->motor_id, (float)angle,
				                      duration_ms);
			} else {
				motor_set_angle(joint->motor_id, (float)angle);
			}
			if (slot >= 0)
				g_servo_current_angle[slot] = (uint16_t)angle;
		}
		break;
	}
	case CMD_ARM_SET_SPEED:
		log_info(TAG, "CMD_ARM_SET_SPEED speed=%u",
		         (unsigned)cmd->cmd.arm_set_speed.speed);
		log_arm_result(
		    "puppyarm_set_speed",
		    puppyarm_set_speed(clamp_arm_speed(cmd->cmd.arm_set_speed.speed)));
		break;
	case CMD_ARM_JOG:
		log_info(TAG, "CMD_ARM_JOG joint=%u direction=%d speed=%u",
		         (unsigned)cmd->cmd.arm_jog.joint,
		         (int)cmd->cmd.arm_jog.direction,
		         (unsigned)cmd->cmd.arm_jog.speed);
		log_arm_result("puppyarm_jog",
		               puppyarm_jog(cmd->cmd.arm_jog.joint,
		                            cmd->cmd.arm_jog.direction,
		                            clamp_arm_speed(cmd->cmd.arm_jog.speed),
		                            platform_get_time_ms()));
		break;
	case CMD_ARM_STOP_JOINT:
		log_info(TAG, "CMD_ARM_STOP_JOINT joint=%u",
		         (unsigned)cmd->cmd.arm_joint.joint);
		log_arm_result("puppyarm_stop_joint",
		               puppyarm_stop_joint(cmd->cmd.arm_joint.joint,
		                                   platform_get_time_ms()));
		break;
	case CMD_ARM_STOP_ALL:
		log_info(TAG, "CMD_ARM_STOP_ALL");
		puppyarm_stop(platform_get_time_ms());
		break;
	case CMD_ARM_GOTO_TICKS:
		log_info(TAG, "CMD_ARM_GOTO_TICKS speed=%u",
		         (unsigned)cmd->cmd.arm_goto_ticks.speed);
		log_arm_result(
		    "puppyarm_goto_ticks",
		    puppyarm_goto_ticks(cmd->cmd.arm_goto_ticks.ticks,
		                        clamp_arm_speed(cmd->cmd.arm_goto_ticks.speed),
		                        platform_get_time_ms()));
		break;
	case CMD_ARM_GOTO_ANGLES: {
		log_info(TAG, "CMD_ARM_GOTO_ANGLES speed=%u",
		         (unsigned)cmd->cmd.arm_goto_angles.speed);
		float angles_rad[PUPPYARM_JOINT_COUNT] = {0};
		for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i)
			angles_rad[i] = deg_to_rad(cmd->cmd.arm_goto_angles.angles_deg[i]);
		log_arm_result(
		    "puppyarm_goto_angles",
		    puppyarm_goto_angles(angles_rad,
		                         clamp_arm_speed(cmd->cmd.arm_goto_angles.speed),
		                         platform_get_time_ms()));
		break;
	}
	case CMD_ARM_GOTO_COORDS:
		log_info(TAG, "CMD_ARM_GOTO_COORDS x=%.1f y=%.1f z=%.1f speed=%u",
		         (double)cmd->cmd.arm_goto_coords.x,
		         (double)cmd->cmd.arm_goto_coords.y,
		         (double)cmd->cmd.arm_goto_coords.z,
		         (unsigned)cmd->cmd.arm_goto_coords.speed);
		log_arm_result(
		    "puppyarm_goto_coords",
		    puppyarm_goto_coords(
		        cmd->cmd.arm_goto_coords.x, cmd->cmd.arm_goto_coords.y,
		        arm_table_z_to_shoulder_z(cmd->cmd.arm_goto_coords.z),
		        clamp_arm_speed(cmd->cmd.arm_goto_coords.speed),
		        platform_get_time_ms()));
		break;
	case CMD_ARM_HOLD:
		log_info(TAG, "CMD_ARM_HOLD speed=%u",
		         (unsigned)cmd->cmd.arm_set_speed.speed);
		log_arm_result("puppyarm_hold",
		               puppyarm_hold(clamp_arm_speed(cmd->cmd.arm_set_speed.speed),
		                             platform_get_time_ms()));
		break;
	case CMD_ARM_SET_JOINT_TICK:
		log_info(TAG, "CMD_ARM_SET_JOINT_TICK joint=%u tick=%" PRId32
		              " speed=%u",
		         (unsigned)cmd->cmd.arm_set_joint_tick.joint,
		         cmd->cmd.arm_set_joint_tick.tick,
		         (unsigned)cmd->cmd.arm_set_joint_tick.speed);
		log_arm_result(
		    "puppyarm_set_joint_tick",
		    puppyarm_set_joint_tick(
		        cmd->cmd.arm_set_joint_tick.joint,
		        cmd->cmd.arm_set_joint_tick.tick,
		        clamp_arm_speed(cmd->cmd.arm_set_joint_tick.speed),
		        platform_get_time_ms()));
		break;
	case CMD_ARM_SET_TICK_LIMITS:
		log_info(TAG, "CMD_ARM_SET_TICK_LIMITS joint=%u min=%" PRId32
		              " max=%" PRId32,
		         (unsigned)cmd->cmd.arm_set_tick_limits.joint,
		         cmd->cmd.arm_set_tick_limits.min_tick,
		         cmd->cmd.arm_set_tick_limits.max_tick);
		log_arm_result(
		    "puppyarm_set_tick_limits",
		    puppyarm_set_tick_limits(cmd->cmd.arm_set_tick_limits.joint,
		                             cmd->cmd.arm_set_tick_limits.min_tick,
		                             cmd->cmd.arm_set_tick_limits.max_tick));
		break;
	case CMD_ARM_SET_TICK_LIMITS_ENABLED:
		log_info(TAG, "CMD_ARM_SET_TICK_LIMITS_ENABLED joint=%u enabled=%u",
		         (unsigned)cmd->cmd.arm_set_tick_limits_enabled.joint,
		         (unsigned)cmd->cmd.arm_set_tick_limits_enabled.enabled);
		log_arm_result("puppyarm_set_tick_limits_enabled",
		               puppyarm_set_tick_limits_enabled(
		                   cmd->cmd.arm_set_tick_limits_enabled.joint,
		                   cmd->cmd.arm_set_tick_limits_enabled.enabled != 0));
		break;
	case CMD_ARM_MOVE_RELATIVE:
		log_info(TAG, "CMD_ARM_MOVE_RELATIVE dx=%.1f dy=%.1f speed=%u",
		         (double)cmd->cmd.arm_move_relative.dx,
		         (double)cmd->cmd.arm_move_relative.dy,
		         (unsigned)cmd->cmd.arm_move_relative.speed);
		log_arm_result(
		    "puppyarm_move_relative",
		    puppyarm_move_relative(
		        cmd->cmd.arm_move_relative.dx, cmd->cmd.arm_move_relative.dy,
		        clamp_arm_speed(cmd->cmd.arm_move_relative.speed),
		        platform_get_time_ms()));
		break;
	case CMD_ARM_CLEAR_FAULTS:
		log_info(TAG, "CMD_ARM_CLEAR_FAULTS joint=%u",
		         (unsigned)cmd->cmd.arm_joint.joint);
		if (cmd->cmd.arm_joint.joint == 255) {
			puppyarm_clear_faults();
		} else {
			log_arm_result("puppyarm_clear_joint_fault",
			               puppyarm_clear_joint_fault(cmd->cmd.arm_joint.joint));
		}
		break;
	case CMD_STOP_MOTOR: {
		log_info(TAG, "CMD_STOP_MOTOR motor %d", cmd->cmd.stop_motor.motor_id);
		uint32_t node_id = (uint32_t)cmd->cmd.stop_motor.motor_id;
		motor_rt_t *motor = find_motor(node_id);
		if (!motor) {
			log_error(TAG, "Unknown motor node %" PRIu32, node_id);
			break;
		}
		if (motor->type_id == MOTOR_TYPE_ANGLE ||
		    motor->type_id == MOTOR_TYPE_SMART) {
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
		log_info(TAG, "CMD_STOP_ALL_MOTORS");
		stop_all_drive_motors();
		puppyarm_stop(platform_get_time_ms());

		if (g_safety_timer) {
			puppy_timer_stop(g_safety_timer);
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
	case CMD_SMARTBUS_SCAN: {
		uint8_t uart_port = (uint8_t)cmd->cmd.smartbus_scan.uart_port;
		uint8_t start_id = (uint8_t)cmd->cmd.smartbus_scan.start_id;
		uint8_t end_id = (uint8_t)cmd->cmd.smartbus_scan.end_id;
		if (start_id == 0)
			start_id = 1;
		if (end_id == 0 || end_id > 253)
			end_id = 253;
		if (start_id > end_id) {
			uint8_t tmp = start_id;
			start_id = end_id;
			end_id = tmp;
		}

		uint8_t found[64];
		uint8_t found_count = 0;
		for (uint16_t id = start_id; id <= end_id && found_count < 64; ++id) {
			if (motor_hw_smartbus_ping(uart_port, (uint8_t)id, 20) == 0) {
				found[found_count++] = (uint8_t)id;
			}
		}
		send_smartbus_scan_result(uart_port, start_id, end_id, found,
		                          found_count);
		break;
	}
	case CMD_SMARTBUS_SET_ID: {
		uint8_t uart_port = (uint8_t)cmd->cmd.smartbus_set_id.uart_port;
		uint8_t old_id = (uint8_t)cmd->cmd.smartbus_set_id.old_id;
		uint8_t new_id = (uint8_t)cmd->cmd.smartbus_set_id.new_id;
		uint8_t status = 1;
		if (old_id > 0 && old_id <= 253 && new_id > 0 && new_id <= 253) {
			motor_hw_smartbus_write_u8(uart_port, old_id, (uint8_t)SMARTBUS_ADDR_LOCK, 0);
			platform_delay_ms(10);
			motor_hw_smartbus_write_u8(uart_port, old_id, 5, new_id);
			platform_delay_ms(50);
			motor_hw_smartbus_write_u8(uart_port, new_id, (uint8_t)SMARTBUS_ADDR_LOCK, 1);
			platform_delay_ms(20);
			status = motor_hw_smartbus_ping(uart_port, new_id, 80) == 0 ? 0 : 2;
		} else {
			status = 3;
		}
		send_smartbus_set_id_result(uart_port, old_id, new_id, status);
		break;
	}
	case CMD_SET_MOTOR_POLL: {
		for (int i = 0; i < motor_count(); ++i) {
			motor_rt_t *m = motor_at(i);
			if (m && m->type_id == MOTOR_TYPE_SMART) {
				m->poll_status = false;
			}
		}
		int n = cmd->cmd.motor_poll.count;
		if (n < 0)
			n = 0;
		if (n > 32)
			n = 32;
		for (int i = 0; i < n; ++i) {
			uint8_t id = cmd->cmd.motor_poll.ids[i];
			if (id == 0)
				continue;
			motor_rt_t *m = find_motor((uint32_t)id);
			if (m && m->type_id == MOTOR_TYPE_SMART) {
				m->poll_status = true;
			}
		}
		break;
	}
	case CMD_SET_BOT_ID: {
		log_info(TAG, "CMD_SET_BOT_ID");
		if (!cmd->cmd.set_bot_id.data || cmd->cmd.set_bot_id.length == 0) {
			log_warn(TAG, "Received empty bot ID payload");
			break;
		}
		const uint8_t *payload = cmd->cmd.set_bot_id.data;
		size_t payload_len = (size_t)cmd->cmd.set_bot_id.length;
		uint8_t id_len = payload[0];
		if (payload_len <= 1 || id_len == 0) {
			log_warn(TAG, "Invalid bot ID payload");
			break;
		}
		size_t available = payload_len - 1;
		size_t copy_len = (size_t)id_len;
		if (copy_len > available) {
			copy_len = available;
		}
		const size_t max_copy = PLATFORM_BOT_ID_MAX_LEN - 1;
		if (copy_len > max_copy) {
			copy_len = max_copy;
		}
		char bot_id[PLATFORM_BOT_ID_MAX_LEN];
		memcpy(bot_id, payload + 1, copy_len);
		bot_id[copy_len] = '\0';
		if (copy_len == 0) {
			log_warn(TAG, "Bot ID payload was empty after trimming");
			break;
		}
		if (platform_store_bot_id(bot_id) != 0) {
			log_error(TAG, "Failed to store bot ID");
		} else {
			log_info(TAG, "Stored new bot ID %s", bot_id);
		}
		break;
	}
	default:
		log_warn(TAG, "Unknown command type: %d", cmd->cmd_type);
		break;
	}
}
