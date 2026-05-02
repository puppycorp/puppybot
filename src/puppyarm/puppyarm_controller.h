#ifndef PUPPYARM_CONTROLLER_H
#define PUPPYARM_CONTROLLER_H

#include <stdbool.h>
#include <stdint.h>

#include "puppyarm/puppyarm_calibration.h"

#define PUPPYARM_FAULT_LEN 64

typedef struct {
	void *ctx;
	int (*enable_wheel_mode)(void *ctx, uint8_t servo_id);
	int (*set_wheel_speed)(void *ctx, uint8_t servo_id, int16_t speed,
	                       uint8_t acc);
	int (*read_position)(void *ctx, uint8_t servo_id, uint16_t *pos_raw_out);
} puppyarm_bus_t;

typedef struct {
	uint8_t servo_id;
	bool online;
	bool has_feedback;
	bool limit_reached;
	int32_t tick;
	int32_t target_tick;
	bool has_target;
	int16_t speed;
	char fault[PUPPYARM_FAULT_LEN];
} puppyarm_joint_state_t;

typedef struct {
	puppyarm_profile_t profile;
	puppyarm_bus_t bus;
	puppyarm_joint_state_t joints[PUPPYARM_JOINT_COUNT];
	uint16_t default_speed;
	uint16_t target_deadband_ticks;
	uint16_t approach_window_ticks;
	uint16_t min_approach_speed;
	uint32_t feedback_timeout_ms;
	uint32_t command_timeout_ms;
	uint32_t last_feedback_ms;
	uint32_t last_command_ms;
	int16_t last_sent_speed[PUPPYARM_JOINT_COUNT];
	bool started;
	char last_error[PUPPYARM_FAULT_LEN];
} puppyarm_controller_t;

int puppyarm_controller_init(puppyarm_controller_t *ctrl,
                             const puppyarm_profile_t *profile,
                             const puppyarm_bus_t *bus, uint32_t now_ms);
int puppyarm_controller_start(puppyarm_controller_t *ctrl, uint32_t now_ms);
void puppyarm_controller_stop_all(puppyarm_controller_t *ctrl,
                                  uint32_t now_ms);
void puppyarm_controller_clear_faults(puppyarm_controller_t *ctrl);
int puppyarm_controller_set_speed(puppyarm_controller_t *ctrl,
                                  uint16_t speed);
int puppyarm_controller_jog(puppyarm_controller_t *ctrl, uint8_t joint,
                            int8_t direction, uint16_t speed,
                            uint32_t now_ms);
int puppyarm_controller_goto_ticks(puppyarm_controller_t *ctrl,
                                   const int32_t ticks[PUPPYARM_JOINT_COUNT],
                                   uint16_t speed, uint32_t now_ms);
int puppyarm_controller_goto_angles(
    puppyarm_controller_t *ctrl,
    const float angles_rad[PUPPYARM_JOINT_COUNT], uint16_t speed,
    uint32_t now_ms);
int puppyarm_controller_goto_coords(puppyarm_controller_t *ctrl, float x_mm,
                                    float y_mm, float z_mm, uint16_t speed,
                                    uint32_t now_ms);
int puppyarm_controller_step(puppyarm_controller_t *ctrl, uint32_t now_ms);
void puppyarm_controller_get_joint_states(
    const puppyarm_controller_t *ctrl,
    puppyarm_joint_state_t out[PUPPYARM_JOINT_COUNT]);
int puppyarm_controller_current_angles(
    const puppyarm_controller_t *ctrl,
    float out_angles_rad[PUPPYARM_JOINT_COUNT]);

#endif
