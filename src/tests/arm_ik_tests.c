#include "arm_ik.h"
#include "test.h"

TEST(arm_ik_solve_straight_reach) {
	arm_config_t cfg = {0};
	cfg.configured = true;
	cfg.joint_count = ARM_IK_MAX_JOINTS;
	cfg.l1 = 1.0f;
	cfg.l2 = 1.0f;
	cfg.z0 = 0.0f;
	for (int i = 0; i < ARM_IK_MAX_JOINTS; ++i) {
		cfg.joints[i].sign = 1;
		cfg.joints[i].offset_deg = 0.0f;
	}

	float out[ARM_IK_MAX_JOINTS] = {0};
	int rc = arm_ik_solve(&cfg, 2.0f, 0.0f, 0.0f, false, out);
	ASSERT_EQ(rc, 0);
	EXPECT_APPROX_EQ(out[0], 0.0f, 0.001f);
	EXPECT_APPROX_EQ(out[1], 0.0f, 0.001f);
	EXPECT_APPROX_EQ(out[2], 0.0f, 0.001f);
}

TEST(arm_ik_solve_out_of_reach) {
	arm_config_t cfg = {0};
	cfg.configured = true;
	cfg.joint_count = ARM_IK_MAX_JOINTS;
	cfg.l1 = 1.0f;
	cfg.l2 = 1.0f;
	cfg.z0 = 0.0f;

	float out[ARM_IK_MAX_JOINTS] = {0};
	int rc = arm_ik_solve(&cfg, 3.0f, 0.0f, 0.0f, false, out);
	ASSERT(rc != 0);
}
