#ifndef PUPPYARM_KINEMATICS_H
#define PUPPYARM_KINEMATICS_H

#include <stdbool.h>
#include <stdint.h>

#include "puppyarm/puppyarm_calibration.h"

#define PUPPYARM_PI 3.14159265358979323846f

typedef struct {
	float yaw;
	float shoulder;
	float elbow;
	float tip;
	bool reachable;
} puppyarm_ik_result_t;

float puppyarm_wrap_pi(float angle_rad);
float puppyarm_zero_offset_from_reference(int32_t tick, int32_t raw_tick_min,
                                          int32_t raw_tick_max, float sign,
                                          float target_angle_rad);
void puppyarm_continuous_tick_interval(int32_t min_tick, int32_t max_tick,
                                       int32_t *lo_out, int32_t *hi_out);
int32_t puppyarm_align_tick_to_reference(int32_t tick, float reference);
int32_t puppyarm_align_tick_to_interval(int32_t tick, int32_t lo, int32_t hi);
int32_t puppyarm_angle_to_tick(const puppyarm_joint_calibration_t *joint,
                               float angle_rad);
float puppyarm_tick_to_angle(const puppyarm_joint_calibration_t *joint,
                             int32_t tick);
int32_t puppyarm_clip_tick_to_limits(const puppyarm_joint_calibration_t *joint,
                                     int32_t tick);
bool puppyarm_tick_within_limits(const puppyarm_joint_calibration_t *joint,
                                 int32_t tick);
float puppyarm_solve_tip_angle_down(float shoulder_rad, float elbow_rad,
                                    float tool_phi_rad);
puppyarm_ik_result_t puppyarm_ik(const puppyarm_profile_t *profile, float x_mm,
                                 float y_mm, float z_mm);
void puppyarm_fk(const puppyarm_profile_t *profile, float yaw_rad,
                 float shoulder_rad, float elbow_rad, float tip_rad,
                 float *x_mm, float *y_mm, float *z_mm);
int puppyarm_solve_coords_exact(const puppyarm_profile_t *profile, float x_mm,
                                float y_mm, float z_mm,
                                float out_angles[PUPPYARM_JOINT_COUNT]);

#endif
