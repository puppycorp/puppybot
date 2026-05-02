#ifndef PUPPYARM_CALIBRATION_H
#define PUPPYARM_CALIBRATION_H

#include <stdbool.h>
#include <stdint.h>

#define PUPPYARM_JOINT_COUNT 4
#define PUPPYARM_TICK_WRAP 4096

typedef enum {
	PUPPYARM_JOINT_YAW = 0,
	PUPPYARM_JOINT_SHOULDER = 1,
	PUPPYARM_JOINT_ELBOW = 2,
	PUPPYARM_JOINT_TIP = 3
} puppyarm_joint_index_t;

typedef struct {
	uint8_t servo_id;
	int32_t tick_min;
	int32_t tick_max;
	int32_t raw_tick_min;
	int32_t raw_tick_max;
	float sign;
	float drive_sign;
	float zero_offset_rad;
	bool limit_enabled;
} puppyarm_joint_calibration_t;

typedef struct {
	float l1_mm;
	float l2_mm;
	float l3_mm;
	float z_origin_mm;
	float tool_phi_rad;
	puppyarm_joint_calibration_t joints[PUPPYARM_JOINT_COUNT];
} puppyarm_profile_t;

#endif
