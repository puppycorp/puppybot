#include "puppyarm/puppyarm_controller.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "puppyarm/puppyarm_kinematics.h"

#define DEFAULT_SPEED 200u
#define TARGET_DEADBAND_TICKS 8u
#define APPROACH_WINDOW_TICKS 80u
#define MIN_APPROACH_SPEED 20u
#define FEEDBACK_TIMEOUT_MS 250u
#define COMMAND_TIMEOUT_MS 1000u

static void set_fault(char fault[PUPPYARM_FAULT_LEN], const char *msg) {
	if (!fault)
		return;
	if (!msg) {
		fault[0] = '\0';
		return;
	}
	snprintf(fault, PUPPYARM_FAULT_LEN, "%s", msg);
}

static bool has_fault(const puppyarm_joint_state_t *joint) {
	return joint && joint->fault[0] != '\0';
}

static int send_speed(puppyarm_controller_t *ctrl, int idx, int16_t speed) {
	if (!ctrl || idx < 0 || idx >= PUPPYARM_JOINT_COUNT ||
	    !ctrl->bus.set_wheel_speed)
		return -1;
	if (ctrl->last_sent_speed[idx] == speed)
		return 0;
	int rc = ctrl->bus.set_wheel_speed(ctrl->bus.ctx, ctrl->joints[idx].servo_id,
	                                   speed, 0);
	if (rc == 0)
		ctrl->last_sent_speed[idx] = speed;
	return rc;
}

static void hard_stop(puppyarm_controller_t *ctrl) {
	if (!ctrl)
		return;
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		ctrl->joints[i].speed = 0;
		ctrl->joints[i].has_target = false;
		(void)send_speed(ctrl, i, 0);
	}
}

static int32_t target_tick_error(const puppyarm_joint_calibration_t *cal,
                                 int32_t target_tick, int32_t current_tick) {
	int32_t lo = 0;
	int32_t hi = 0;
	puppyarm_continuous_tick_interval(cal->tick_min, cal->tick_max, &lo, &hi);
	int32_t target = puppyarm_align_tick_to_interval(target_tick, lo, hi);
	int32_t current = puppyarm_align_tick_to_interval(current_tick, lo, hi);
	return target - current;
}

static bool speed_hits_limit(const puppyarm_joint_calibration_t *cal,
                             const puppyarm_joint_state_t *state,
                             int16_t speed) {
	if (!cal || !state || !cal->limit_enabled || !state->has_feedback ||
	    speed == 0)
		return false;
	int32_t lo = 0;
	int32_t hi = 0;
	puppyarm_continuous_tick_interval(cal->tick_min, cal->tick_max, &lo, &hi);
	int32_t tick = puppyarm_align_tick_to_interval(state->tick, lo, hi);
	if (speed > 0)
		return tick >= hi;
	return tick <= lo;
}

static int16_t tracking_speed(const puppyarm_controller_t *ctrl, int idx) {
	const puppyarm_joint_calibration_t *cal = &ctrl->profile.joints[idx];
	const puppyarm_joint_state_t *state = &ctrl->joints[idx];
	if (!state->has_target || !state->has_feedback)
		return 0;

	int32_t err = target_tick_error(cal, state->target_tick, state->tick);
	if (err < 0 ? -err <= (int32_t)ctrl->target_deadband_ticks
	            : err <= (int32_t)ctrl->target_deadband_ticks) {
		return 0;
	}

	int32_t abs_err = err < 0 ? -err : err;
	int32_t speed = (int32_t)ctrl->default_speed;
	if (abs_err < (int32_t)ctrl->approach_window_ticks) {
		speed = (speed * abs_err) / (int32_t)ctrl->approach_window_ticks;
		if (speed < (int32_t)ctrl->min_approach_speed)
			speed = (int32_t)ctrl->min_approach_speed;
	}
	if (speed < 0)
		speed = 0;
	if (speed > 1000)
		speed = 1000;
	if (err < 0)
		speed = -speed;
	speed = (int32_t)lroundf((float)speed * cal->drive_sign);
	if (speed > 1000)
		speed = 1000;
	if (speed < -1000)
		speed = -1000;
	return (int16_t)speed;
}

int puppyarm_controller_init(puppyarm_controller_t *ctrl,
                             const puppyarm_profile_t *profile,
                             const puppyarm_bus_t *bus, uint32_t now_ms) {
	if (!ctrl || !profile || !bus || !bus->read_position ||
	    !bus->set_wheel_speed)
		return -1;
	memset(ctrl, 0, sizeof(*ctrl));
	ctrl->profile = *profile;
	ctrl->bus = *bus;
	ctrl->default_speed = DEFAULT_SPEED;
	ctrl->target_deadband_ticks = TARGET_DEADBAND_TICKS;
	ctrl->approach_window_ticks = APPROACH_WINDOW_TICKS;
	ctrl->min_approach_speed = MIN_APPROACH_SPEED;
	ctrl->feedback_timeout_ms = FEEDBACK_TIMEOUT_MS;
	ctrl->command_timeout_ms = COMMAND_TIMEOUT_MS;
	ctrl->last_feedback_ms = now_ms;
	ctrl->last_command_ms = now_ms;
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		ctrl->joints[i].servo_id = profile->joints[i].servo_id;
		ctrl->joints[i].online = true;
		ctrl->last_sent_speed[i] = INT16_MIN;
	}
	return 0;
}

int puppyarm_controller_start(puppyarm_controller_t *ctrl, uint32_t now_ms) {
	if (!ctrl)
		return -1;
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		if (ctrl->bus.enable_wheel_mode) {
			int rc = ctrl->bus.enable_wheel_mode(
			    ctrl->bus.ctx, ctrl->joints[i].servo_id);
			if (rc != 0) {
				set_fault(ctrl->joints[i].fault, "wheel mode failed");
				return rc;
			}
		}
		(void)send_speed(ctrl, i, 0);
	}
	ctrl->started = true;
	ctrl->last_command_ms = now_ms;
	return 0;
}

void puppyarm_controller_stop_all(puppyarm_controller_t *ctrl,
                                  uint32_t now_ms) {
	if (!ctrl)
		return;
	hard_stop(ctrl);
	ctrl->last_command_ms = now_ms;
}

int puppyarm_controller_stop_joint(puppyarm_controller_t *ctrl, uint8_t joint,
                                   uint32_t now_ms) {
	if (!ctrl || joint >= PUPPYARM_JOINT_COUNT)
		return -1;
	ctrl->joints[joint].speed = 0;
	ctrl->joints[joint].has_target = false;
	int rc = send_speed(ctrl, joint, 0);
	ctrl->last_command_ms = now_ms;
	return rc;
}

void puppyarm_controller_clear_faults(puppyarm_controller_t *ctrl) {
	if (!ctrl)
		return;
	ctrl->last_error[0] = '\0';
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i)
		ctrl->joints[i].fault[0] = '\0';
}

int puppyarm_controller_clear_joint_fault(puppyarm_controller_t *ctrl,
                                          uint8_t joint) {
	if (!ctrl || joint >= PUPPYARM_JOINT_COUNT)
		return -1;
	ctrl->joints[joint].fault[0] = '\0';
	ctrl->last_error[0] = '\0';
	return 0;
}

int puppyarm_controller_set_speed(puppyarm_controller_t *ctrl,
                                  uint16_t speed) {
	if (!ctrl)
		return -1;
	if (speed > 1000)
		speed = 1000;
	ctrl->default_speed = speed;
	if (speed == 0) {
		hard_stop(ctrl);
		return 0;
	}
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		puppyarm_joint_state_t *joint = &ctrl->joints[i];
		if (joint->has_target || joint->speed == 0)
			continue;
		joint->speed = joint->speed > 0 ? (int16_t)speed : -(int16_t)speed;
	}
	return 0;
}

int puppyarm_controller_jog(puppyarm_controller_t *ctrl, uint8_t joint,
                            int8_t direction, uint16_t speed,
                            uint32_t now_ms) {
	if (!ctrl || joint >= PUPPYARM_JOINT_COUNT)
		return -1;
	if (speed > 0)
		ctrl->default_speed = speed > 1000 ? 1000 : speed;
	puppyarm_joint_state_t *state = &ctrl->joints[joint];
	state->has_target = false;
	if (direction > 0)
		state->speed = (int16_t)ctrl->default_speed;
	else if (direction < 0)
		state->speed = -(int16_t)ctrl->default_speed;
	else
		state->speed = 0;
	state->speed = (int16_t)lroundf(
	    (float)state->speed * ctrl->profile.joints[joint].drive_sign);
	state->fault[0] = '\0';
	ctrl->last_command_ms = now_ms;
	return 0;
}

int puppyarm_controller_goto_ticks(puppyarm_controller_t *ctrl,
                                   const int32_t ticks[PUPPYARM_JOINT_COUNT],
                                   uint16_t speed, uint32_t now_ms) {
	if (!ctrl || !ticks)
		return -1;
	if (speed > 0)
		ctrl->default_speed = speed > 1000 ? 1000 : speed;
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		int32_t tick = ticks[i];
		if (ctrl->profile.joints[i].limit_enabled)
			tick = puppyarm_clip_tick_to_limits(&ctrl->profile.joints[i], tick);
		ctrl->joints[i].target_tick = tick;
		ctrl->joints[i].has_target = true;
		ctrl->joints[i].fault[0] = '\0';
	}
	ctrl->last_command_ms = now_ms;
	return 0;
}

int puppyarm_controller_goto_angles(
    puppyarm_controller_t *ctrl,
    const float angles_rad[PUPPYARM_JOINT_COUNT], uint16_t speed,
    uint32_t now_ms) {
	if (!ctrl || !angles_rad)
		return -1;
	int32_t ticks[PUPPYARM_JOINT_COUNT] = {0};
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i)
		ticks[i] = puppyarm_angle_to_tick(&ctrl->profile.joints[i],
		                                  angles_rad[i]);
	return puppyarm_controller_goto_ticks(ctrl, ticks, speed, now_ms);
}

int puppyarm_controller_goto_coords(puppyarm_controller_t *ctrl, float x_mm,
                                    float y_mm, float z_mm, uint16_t speed,
                                    uint32_t now_ms) {
	if (!ctrl)
		return -1;
	float angles[PUPPYARM_JOINT_COUNT] = {0};
	int rc = puppyarm_solve_coords_exact(&ctrl->profile, x_mm, y_mm, z_mm,
	                                     angles);
	if (rc != 0) {
		snprintf(ctrl->last_error, sizeof(ctrl->last_error),
		         "unreachable coords %.1f %.1f %.1f", (double)x_mm,
		         (double)y_mm, (double)z_mm);
		return rc;
	}
	return puppyarm_controller_goto_angles(ctrl, angles, speed, now_ms);
}

int puppyarm_controller_hold(puppyarm_controller_t *ctrl, uint16_t speed,
                             uint32_t now_ms) {
	if (!ctrl)
		return -1;
	int32_t ticks[PUPPYARM_JOINT_COUNT] = {0};
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		if (!ctrl->joints[i].has_feedback) {
			snprintf(ctrl->last_error, sizeof(ctrl->last_error),
			         "missing feedback for hold");
			return -2;
		}
		ticks[i] = ctrl->joints[i].tick;
	}
	return puppyarm_controller_goto_ticks(ctrl, ticks, speed, now_ms);
}

int puppyarm_controller_set_joint_tick(puppyarm_controller_t *ctrl,
                                       uint8_t joint, int32_t tick,
                                       uint16_t speed, uint32_t now_ms) {
	if (!ctrl || joint >= PUPPYARM_JOINT_COUNT)
		return -1;
	int32_t ticks[PUPPYARM_JOINT_COUNT] = {0};
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		if (!ctrl->joints[i].has_feedback) {
			snprintf(ctrl->last_error, sizeof(ctrl->last_error),
			         "missing feedback for joint tick move");
			return -2;
		}
		ticks[i] = ctrl->joints[i].tick;
	}
	ticks[joint] = tick;
	return puppyarm_controller_goto_ticks(ctrl, ticks, speed, now_ms);
}

int puppyarm_controller_set_tick_limits(puppyarm_controller_t *ctrl,
                                        uint8_t joint, int32_t min_tick,
                                        int32_t max_tick) {
	if (!ctrl || joint >= PUPPYARM_JOINT_COUNT || min_tick == max_tick)
		return -1;
	ctrl->profile.joints[joint].tick_min = min_tick;
	ctrl->profile.joints[joint].tick_max = max_tick;
	return 0;
}

int puppyarm_controller_set_tick_limits_enabled(puppyarm_controller_t *ctrl,
                                                uint8_t joint, bool enabled) {
	if (!ctrl || joint >= PUPPYARM_JOINT_COUNT)
		return -1;
	ctrl->profile.joints[joint].limit_enabled = enabled;
	return 0;
}

int puppyarm_controller_move_relative(puppyarm_controller_t *ctrl, float dx_mm,
                                      float dy_mm, uint16_t speed,
                                      uint32_t now_ms) {
	if (!ctrl)
		return -1;
	float angles[PUPPYARM_JOINT_COUNT] = {0};
	if (puppyarm_controller_current_angles(ctrl, angles) != 0) {
		snprintf(ctrl->last_error, sizeof(ctrl->last_error),
		         "missing feedback for relative move");
		return -2;
	}
	float x = 0.0f;
	float y = 0.0f;
	float z = 0.0f;
	puppyarm_fk(&ctrl->profile, angles[0], angles[1], angles[2], angles[3], &x,
	            &y, &z);
	return puppyarm_controller_goto_coords(ctrl, x + dx_mm, y + dy_mm, z,
	                                       speed, now_ms);
}

static void read_feedback(puppyarm_controller_t *ctrl, uint32_t now_ms) {
	bool any_ok = false;
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		uint16_t raw = 0;
		int rc = ctrl->bus.read_position(ctrl->bus.ctx,
		                                 ctrl->joints[i].servo_id, &raw);
		if (rc != 0) {
			ctrl->joints[i].online = false;
			ctrl->joints[i].has_feedback = false;
			continue;
		}
		ctrl->joints[i].online = true;
		ctrl->joints[i].has_feedback = true;
		ctrl->joints[i].tick = (int32_t)raw;
		any_ok = true;
	}
	if (any_ok)
		ctrl->last_feedback_ms = now_ms;
}

int puppyarm_controller_step(puppyarm_controller_t *ctrl, uint32_t now_ms) {
	if (!ctrl)
		return -1;
	read_feedback(ctrl, now_ms);

	if ((uint32_t)(now_ms - ctrl->last_feedback_ms) >
	    ctrl->feedback_timeout_ms) {
		snprintf(ctrl->last_error, sizeof(ctrl->last_error),
		         "deadman stop: feedback stale");
		hard_stop(ctrl);
		return -2;
	}

	bool has_free_jog = false;
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		if (!ctrl->joints[i].has_target && ctrl->joints[i].speed != 0)
			has_free_jog = true;
	}
	if (has_free_jog &&
	    (uint32_t)(now_ms - ctrl->last_command_ms) > ctrl->command_timeout_ms) {
		snprintf(ctrl->last_error, sizeof(ctrl->last_error),
		         "deadman stop: command stale");
		hard_stop(ctrl);
		return -3;
	}

	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		puppyarm_joint_state_t *state = &ctrl->joints[i];
		const puppyarm_joint_calibration_t *cal = &ctrl->profile.joints[i];
		int16_t speed = 0;

		state->limit_reached =
		    cal->limit_enabled && state->has_feedback &&
		    !puppyarm_tick_within_limits(cal, state->tick);
		if (state->has_target && !state->has_feedback) {
			set_fault(state->fault, "feedback unavailable");
		}

		speed = state->has_target ? tracking_speed(ctrl, i) : state->speed;
		if (state->has_target && state->has_feedback && speed == 0) {
			state->has_target = false;
		}

		if (!state->has_feedback && speed != 0) {
			set_fault(state->fault, "feedback unavailable");
			speed = 0;
		}
		if (has_fault(state))
			speed = 0;
		if (speed_hits_limit(cal, state, speed)) {
			set_fault(state->fault, "limit reached");
			speed = 0;
		}
		state->speed = speed;
		int rc = send_speed(ctrl, i, speed);
		if (rc != 0)
			return rc;
	}
	return 0;
}

void puppyarm_controller_get_joint_states(
    const puppyarm_controller_t *ctrl,
    puppyarm_joint_state_t out[PUPPYARM_JOINT_COUNT]) {
	if (!ctrl || !out)
		return;
	memcpy(out, ctrl->joints, sizeof(ctrl->joints));
}

int puppyarm_controller_current_angles(
    const puppyarm_controller_t *ctrl,
    float out_angles_rad[PUPPYARM_JOINT_COUNT]) {
	if (!ctrl || !out_angles_rad)
		return -1;
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		if (!ctrl->joints[i].has_feedback)
			return -2;
		out_angles_rad[i] = puppyarm_tick_to_angle(&ctrl->profile.joints[i],
		                                           ctrl->joints[i].tick);
	}
	return 0;
}
