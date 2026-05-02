#ifndef ARM_IK_H
#define ARM_IK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ARM_IK_MAX_JOINTS 3

typedef struct {
	uint32_t motor_id;
	int8_t sign;
	float offset_deg;
} arm_joint_map_t;

typedef struct {
	bool configured;
	uint8_t joint_count;
	float l1;
	float l2;
	float z0;
	arm_joint_map_t joints[ARM_IK_MAX_JOINTS];
} arm_config_t;

void arm_config_reset(void);
const arm_config_t *arm_config_get(void);
int arm_config_apply_pbcl(const uint8_t *tlvs, size_t tlv_len);

int arm_ik_solve(const arm_config_t *config, float x, float y, float z,
                 bool elbow_up, float out_deg[ARM_IK_MAX_JOINTS]);

#endif
