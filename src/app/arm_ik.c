#include "arm_ik.h"

#include <math.h>
#include <string.h>

#include "log.h"
#include "pbcl.h"
#include "pbcl_tags.h"

#define TAG "ARM_IK"

static arm_config_t g_arm_config = {0};

static float read_float_le(const uint8_t *data) {
	uint32_t raw = (uint32_t)data[0] | ((uint32_t)data[1] << 8) |
	               ((uint32_t)data[2] << 16) | ((uint32_t)data[3] << 24);
	float value = 0.0f;
	memcpy(&value, &raw, sizeof(value));
	return value;
}

static uint8_t clamp_joint_count(int count) {
	if (count < 0)
		return 0;
	if (count > ARM_IK_MAX_JOINTS)
		return ARM_IK_MAX_JOINTS;
	return (uint8_t)count;
}

void arm_config_reset(void) {
	memset(&g_arm_config, 0, sizeof(g_arm_config));
}

const arm_config_t *arm_config_get(void) {
	return &g_arm_config;
}

int arm_config_apply_pbcl(const uint8_t *tlvs, size_t tlv_len) {
	if (!tlvs || tlv_len == 0) {
		arm_config_reset();
		return -1;
	}

	arm_config_t next = {0};
	for (size_t i = 0; i < ARM_IK_MAX_JOINTS; ++i) {
		next.joints[i].sign = 1;
	}

	uint8_t joint_count = 0;
	const uint8_t *ptr = tlvs;
	const uint8_t *end = tlvs + tlv_len;
	while ((size_t)(end - ptr) >= sizeof(pbcl_tlv_t)) {
		const pbcl_tlv_t *tlv = (const pbcl_tlv_t *)ptr;
		const size_t total = sizeof(pbcl_tlv_t) + tlv->len;
		if ((size_t)(end - ptr) < total)
			break;
		const uint8_t *val = ptr + sizeof(pbcl_tlv_t);
		switch (tlv->tag) {
		case PBCL_T_ARM_JOINTS:
			if (tlv->len >= 1) {
				joint_count = clamp_joint_count(val[0]);
				next.joint_count = joint_count;
			}
			break;
		case PBCL_T_ARM_GEOMETRY:
			if (tlv->len >= 12) {
				next.l1 = read_float_le(val);
				next.l2 = read_float_le(val + 4);
				next.z0 = read_float_le(val + 8);
			}
			break;
		case PBCL_T_ARM_JOINT_MAP: {
			uint8_t count = joint_count;
			if (count == 0)
				count = clamp_joint_count((int)(tlv->len / 4));
			for (uint8_t i = 0; i < count && (i * 4 + 4) <= tlv->len; ++i) {
				const uint8_t *slot = val + i * 4;
				uint32_t motor_id = (uint32_t)slot[0] |
				                    ((uint32_t)slot[1] << 8) |
				                    ((uint32_t)slot[2] << 16) |
				                    ((uint32_t)slot[3] << 24);
				next.joints[i].motor_id = motor_id;
			}
			if (next.joint_count == 0)
				next.joint_count = count;
			break;
		}
		case PBCL_T_ARM_SERVO_MAP: {
			uint8_t count = joint_count;
			if (count == 0)
				count = clamp_joint_count((int)(tlv->len / 3));
			for (uint8_t i = 0; i < count && (i * 3 + 3) <= tlv->len; ++i) {
				const uint8_t *slot = val + i * 3;
				int8_t sign = (int8_t)slot[0];
				int16_t offset_x10 =
				    (int16_t)(slot[1] | ((int16_t)slot[2] << 8));
				next.joints[i].sign = (sign < 0) ? -1 : 1;
				next.joints[i].offset_deg = ((float)offset_x10) / 10.0f;
			}
			if (next.joint_count == 0)
				next.joint_count = count;
			break;
		}
		}
		ptr += total;
	}

	if (next.joint_count > ARM_IK_MAX_JOINTS)
		next.joint_count = ARM_IK_MAX_JOINTS;
	next.configured =
	    (next.joint_count == ARM_IK_MAX_JOINTS && next.l1 > 0.0f &&
	     next.l2 > 0.0f);

	g_arm_config = next;

	log_info(TAG, "Arm config joints=%u l1=%.3f l2=%.3f z0=%.3f",
	         g_arm_config.joint_count, (double)g_arm_config.l1,
	         (double)g_arm_config.l2, (double)g_arm_config.z0);
	return 0;
}

static float clampf(float value, float min, float max) {
	if (value < min)
		return min;
	if (value > max)
		return max;
	return value;
}

int arm_ik_solve(const arm_config_t *config, float x, float y, float z,
                 bool elbow_up, float out_deg[ARM_IK_MAX_JOINTS]) {
	if (!config || !out_deg)
		return -1;
	if (!config->configured)
		return -2;
	if (config->joint_count != ARM_IK_MAX_JOINTS)
		return -3;

	float l1 = config->l1;
	float l2 = config->l2;
	float z0 = config->z0;
	if (l1 <= 0.0f || l2 <= 0.0f)
		return -4;

	float r = sqrtf(x * x + y * y);
	float z1 = z - z0;
	float d2 = r * r + z1 * z1;
	float cos_elbow = (d2 - l1 * l1 - l2 * l2) / (2.0f * l1 * l2);
	if (!isfinite(cos_elbow) || cos_elbow < -1.0f || cos_elbow > 1.0f)
		return -5;

	float elbow = acosf(clampf(cos_elbow, -1.0f, 1.0f));
	if (elbow_up)
		elbow = -elbow;

	float shoulder = atan2f(z1, r) -
	                 atan2f(l2 * sinf(elbow), l1 + l2 * cosf(elbow));
	float base = atan2f(y, x);

	const float rad_to_deg = 180.0f / 3.14159265358979323846f;
	out_deg[0] = base * rad_to_deg;
	out_deg[1] = shoulder * rad_to_deg;
	out_deg[2] = elbow * rad_to_deg;
	return 0;
}
