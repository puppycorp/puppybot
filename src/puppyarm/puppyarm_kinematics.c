#include "puppyarm/puppyarm_kinematics.h"

#include <math.h>
#include <stddef.h>

static float clampf_local(float value, float lo, float hi) {
	if (value < lo)
		return lo;
	if (value > hi)
		return hi;
	return value;
}

float puppyarm_wrap_pi(float angle_rad) {
	while (angle_rad > PUPPYARM_PI)
		angle_rad -= 2.0f * PUPPYARM_PI;
	while (angle_rad < -PUPPYARM_PI)
		angle_rad += 2.0f * PUPPYARM_PI;
	return angle_rad;
}

void puppyarm_continuous_tick_interval(int32_t min_tick, int32_t max_tick,
                                       int32_t *lo_out, int32_t *hi_out) {
	int32_t lo = min_tick;
	int32_t hi = max_tick;
	if (lo > hi)
		hi += PUPPYARM_TICK_WRAP;
	if (lo_out)
		*lo_out = lo;
	if (hi_out)
		*hi_out = hi;
}

int32_t puppyarm_align_tick_to_reference(int32_t tick, float reference) {
	int32_t best = tick;
	float best_dist = fabsf((float)tick - reference);
	for (int k = -2; k <= 2; ++k) {
		int32_t candidate = tick + k * PUPPYARM_TICK_WRAP;
		float dist = fabsf((float)candidate - reference);
		if (dist < best_dist) {
			best = candidate;
			best_dist = dist;
		}
	}
	return best;
}

int32_t puppyarm_align_tick_to_interval(int32_t tick, int32_t lo, int32_t hi) {
	int32_t best = tick;
	int32_t best_interval_dist = 0x7fffffff;
	int32_t best_origin_dist = 0x7fffffff;
	for (int k = -2; k <= 2; ++k) {
		int32_t candidate = tick + k * PUPPYARM_TICK_WRAP;
		int32_t interval_dist = 0;
		if (candidate < lo)
			interval_dist = lo - candidate;
		else if (candidate > hi)
			interval_dist = candidate - hi;
		int32_t origin_dist = candidate > tick ? candidate - tick : tick - candidate;
		if (interval_dist < best_interval_dist ||
		    (interval_dist == best_interval_dist &&
		     origin_dist < best_origin_dist)) {
			best = candidate;
			best_interval_dist = interval_dist;
			best_origin_dist = origin_dist;
		}
	}
	return best;
}

float puppyarm_zero_offset_from_reference(int32_t tick, int32_t raw_tick_min,
                                          int32_t raw_tick_max, float sign,
                                          float target_angle_rad) {
	int32_t lo = 0;
	int32_t hi = 0;
	puppyarm_continuous_tick_interval(raw_tick_min, raw_tick_max, &lo, &hi);
	float mid_tick = 0.5f * (float)(lo + hi);
	int32_t aligned = puppyarm_align_tick_to_reference(tick, mid_tick);
	float physical_angle =
	    ((float)aligned - mid_tick) * (2.0f * PUPPYARM_PI /
	                                  (float)PUPPYARM_TICK_WRAP);
	return physical_angle - (sign * target_angle_rad);
}

static float joint_mid_tick(const puppyarm_joint_calibration_t *joint) {
	int32_t lo = 0;
	int32_t hi = 0;
	puppyarm_continuous_tick_interval(joint->raw_tick_min,
	                                  joint->raw_tick_max, &lo, &hi);
	return 0.5f * (float)(lo + hi);
}

int32_t puppyarm_angle_to_tick(const puppyarm_joint_calibration_t *joint,
                               float angle_rad) {
	if (!joint)
		return 0;
	float physical_angle = joint->sign * angle_rad + joint->zero_offset_rad;
	float tick = joint_mid_tick(joint) +
	             physical_angle * (float)PUPPYARM_TICK_WRAP /
	                 (2.0f * PUPPYARM_PI);
	return (int32_t)lroundf(tick);
}

float puppyarm_tick_to_angle(const puppyarm_joint_calibration_t *joint,
                             int32_t tick) {
	if (!joint || joint->sign == 0.0f)
		return 0.0f;
	float mid_tick = joint_mid_tick(joint);
	int32_t aligned = puppyarm_align_tick_to_reference(tick, mid_tick);
	float physical_angle =
	    ((float)aligned - mid_tick) * (2.0f * PUPPYARM_PI /
	                                  (float)PUPPYARM_TICK_WRAP);
	return (physical_angle - joint->zero_offset_rad) / joint->sign;
}

int32_t puppyarm_clip_tick_to_limits(const puppyarm_joint_calibration_t *joint,
                                     int32_t tick) {
	if (!joint || !joint->limit_enabled)
		return tick;
	int32_t lo = 0;
	int32_t hi = 0;
	puppyarm_continuous_tick_interval(joint->tick_min, joint->tick_max, &lo,
	                                  &hi);
	int32_t aligned = puppyarm_align_tick_to_interval(tick, lo, hi);
	if (aligned < lo)
		return lo;
	if (aligned > hi)
		return hi;
	return aligned;
}

bool puppyarm_tick_within_limits(const puppyarm_joint_calibration_t *joint,
                                 int32_t tick) {
	if (!joint || !joint->limit_enabled)
		return true;
	int32_t lo = 0;
	int32_t hi = 0;
	puppyarm_continuous_tick_interval(joint->tick_min, joint->tick_max, &lo,
	                                  &hi);
	int32_t aligned = puppyarm_align_tick_to_interval(tick, lo, hi);
	return aligned >= lo && aligned <= hi;
}

float puppyarm_solve_tip_angle_down(float shoulder_rad, float elbow_rad,
                                    float tool_phi_rad) {
	return puppyarm_wrap_pi(shoulder_rad - elbow_rad - tool_phi_rad);
}

puppyarm_ik_result_t puppyarm_ik(const puppyarm_profile_t *profile, float x_mm,
                                 float y_mm, float z_mm) {
	puppyarm_ik_result_t result = {0};
	if (!profile || profile->l1_mm <= 0.0f || profile->l2_mm <= 0.0f)
		return result;

	float yaw = 0.0f;
	float r_xy = 0.0f;
	if (x_mm * x_mm + y_mm * y_mm >= 1e-12f) {
		yaw = atan2f(y_mm, -x_mm);
		r_xy = sqrtf(x_mm * x_mm + y_mm * y_mm);
	}

	float rw = r_xy;
	float zw = z_mm + profile->l3_mm;
	float l1 = profile->l1_mm;
	float l2 = profile->l2_mm;
	float d2 = rw * rw + zw * zw;
	float cos_elbow = (d2 - l1 * l1 - l2 * l2) / (2.0f * l1 * l2);
	result.reachable = cos_elbow >= -1.0f && cos_elbow <= 1.0f;
	cos_elbow = clampf_local(cos_elbow, -1.0f, 1.0f);

	float gamma = -acosf(cos_elbow);
	float k1 = l1 + l2 * cosf(gamma);
	float k2 = l2 * sinf(gamma);
	float shoulder = atan2f(zw, rw) - atan2f(k2, k1);
	float elbow = -gamma;
	float tip =
	    puppyarm_solve_tip_angle_down(shoulder, elbow, profile->tool_phi_rad);

	result.yaw = puppyarm_wrap_pi(yaw);
	result.shoulder = shoulder;
	result.elbow = elbow;
	result.tip = tip;
	return result;
}

void puppyarm_fk(const puppyarm_profile_t *profile, float yaw_rad,
                 float shoulder_rad, float elbow_rad, float tip_rad,
                 float *x_mm, float *y_mm, float *z_mm) {
	if (!profile)
		return;
	float link2_pitch = shoulder_rad - elbow_rad;
	float tool_pitch = link2_pitch - tip_rad;
	float r = profile->l1_mm * cosf(shoulder_rad) +
	          profile->l2_mm * cosf(link2_pitch) +
	          profile->l3_mm * cosf(tool_pitch);
	if (x_mm)
		*x_mm = -r * cosf(yaw_rad);
	if (y_mm)
		*y_mm = r * sinf(yaw_rad);
	if (z_mm)
		*z_mm = profile->l1_mm * sinf(shoulder_rad) +
		        profile->l2_mm * sinf(link2_pitch) +
		        profile->l3_mm * sinf(tool_pitch);
}

int puppyarm_solve_coords_exact(const puppyarm_profile_t *profile, float x_mm,
                                float y_mm, float z_mm,
                                float out_angles[PUPPYARM_JOINT_COUNT]) {
	if (!profile || !out_angles)
		return -1;
	puppyarm_ik_result_t ik = puppyarm_ik(profile, x_mm, y_mm, z_mm);
	if (!ik.reachable)
		return -2;

	float angles[PUPPYARM_JOINT_COUNT] = {ik.yaw, ik.shoulder, ik.elbow,
	                                      ik.tip};
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		int32_t tick = puppyarm_angle_to_tick(&profile->joints[i], angles[i]);
		if (!puppyarm_tick_within_limits(&profile->joints[i], tick))
			return -3;
		out_angles[i] = angles[i];
	}
	return 0;
}
