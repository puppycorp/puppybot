#include "puppyarm/puppyarm.h"
#include "test.h"

#include <math.h>
#include <stdbool.h>
#include <string.h>

typedef struct {
	uint16_t pos[PUPPYARM_JOINT_COUNT];
	int16_t speed[PUPPYARM_JOINT_COUNT];
	int wheel_mode_calls;
	int speed_calls;
	int read_calls;
	int last_speed_servo;
	int read_rc;
	int wheel_mode_rc;
} fake_arm_bus_t;

static int fake_enable_wheel_mode(void *ctx, uint8_t servo_id) {
	(void)servo_id;
	fake_arm_bus_t *bus = (fake_arm_bus_t *)ctx;
	bus->wheel_mode_calls++;
	return bus->wheel_mode_rc;
}

static int fake_set_wheel_speed(void *ctx, uint8_t servo_id, int16_t speed,
                                uint8_t acc) {
	(void)acc;
	fake_arm_bus_t *bus = (fake_arm_bus_t *)ctx;
	if (servo_id == 0 || servo_id > PUPPYARM_JOINT_COUNT)
		return -1;
	bus->speed[servo_id - 1] = speed;
	bus->speed_calls++;
	bus->last_speed_servo = servo_id;
	return 0;
}

static int fake_read_position(void *ctx, uint8_t servo_id,
                              uint16_t *pos_raw_out) {
	fake_arm_bus_t *bus = (fake_arm_bus_t *)ctx;
	if (servo_id == 0 || servo_id > PUPPYARM_JOINT_COUNT || !pos_raw_out)
		return -1;
	bus->read_calls++;
	if (bus->read_rc != 0)
		return bus->read_rc;
	*pos_raw_out = bus->pos[servo_id - 1];
	return 0;
}

static puppyarm_bus_t make_fake_bus(fake_arm_bus_t *fake) {
	puppyarm_bus_t bus = {
	    .ctx = fake,
	    .enable_wheel_mode = fake_enable_wheel_mode,
	    .set_wheel_speed = fake_set_wheel_speed,
	    .read_position = fake_read_position,
	};
	return bus;
}

static void make_simple_profile(puppyarm_profile_t *profile) {
	memset(profile, 0, sizeof(*profile));
	profile->l1_mm = 100.0f;
	profile->l2_mm = 100.0f;
	profile->l3_mm = 50.0f;
	profile->tool_phi_rad = -PUPPYARM_PI / 2.0f;
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		profile->joints[i].servo_id = (uint8_t)(i + 1);
		profile->joints[i].tick_min = 0;
		profile->joints[i].tick_max = 4095;
		profile->joints[i].raw_tick_min = 0;
		profile->joints[i].raw_tick_max = 4095;
		profile->joints[i].sign = 1.0f;
		profile->joints[i].drive_sign = 1.0f;
		profile->joints[i].limit_enabled = true;
	}
}

static void make_started_controller(puppyarm_controller_t *ctrl,
                                    puppyarm_profile_t *profile,
                                    fake_arm_bus_t *fake) {
	make_simple_profile(profile);
	memset(fake, 0, sizeof(*fake));
	puppyarm_bus_t bus = make_fake_bus(fake);
	ASSERT_EQ(puppyarm_controller_init(ctrl, profile, &bus, 0), 0);
	ASSERT_EQ(puppyarm_controller_start(ctrl, 0), 0);
}

static int any_target_set(const puppyarm_controller_t *ctrl) {
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i) {
		if (ctrl->joints[i].has_target)
			return 1;
	}
	return 0;
}

static void set_all_positions(fake_arm_bus_t *fake, uint16_t value) {
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i)
		fake->pos[i] = value;
}

TEST(puppyarm_wrap_pi_matches_roboband_cases) {
	EXPECT_APPROX_EQ(puppyarm_wrap_pi(0.0f), 0.0f, 0.0001f);
	EXPECT_APPROX_EQ(puppyarm_wrap_pi(PUPPYARM_PI / 3.0f),
	                 PUPPYARM_PI / 3.0f, 0.0001f);
	EXPECT_APPROX_EQ(puppyarm_wrap_pi(-PUPPYARM_PI / 4.0f),
	                 -PUPPYARM_PI / 4.0f, 0.0001f);
	EXPECT_APPROX_EQ(puppyarm_wrap_pi(PUPPYARM_PI), PUPPYARM_PI, 0.0001f);
	EXPECT_APPROX_EQ(puppyarm_wrap_pi(-PUPPYARM_PI), -PUPPYARM_PI, 0.0001f);
	EXPECT_APPROX_EQ(puppyarm_wrap_pi(PUPPYARM_PI + 0.1f),
	                 -PUPPYARM_PI + 0.1f, 0.0001f);
	EXPECT_APPROX_EQ(puppyarm_wrap_pi(-PUPPYARM_PI - 0.1f),
	                 PUPPYARM_PI - 0.1f, 0.0001f);
	EXPECT_APPROX_EQ(puppyarm_wrap_pi(3.0f * PUPPYARM_PI), PUPPYARM_PI,
	                 0.0001f);
	EXPECT_APPROX_EQ(puppyarm_wrap_pi(2.5f * PUPPYARM_PI),
	                 PUPPYARM_PI / 2.0f, 0.0001f);
	EXPECT_APPROX_EQ(puppyarm_wrap_pi(-2.5f * PUPPYARM_PI),
	                 -PUPPYARM_PI / 2.0f, 0.0001f);
}

TEST(puppyarm_tick_alignment_handles_wrap_intervals) {
	int32_t lo = 0;
	int32_t hi = 0;
	puppyarm_continuous_tick_interval(3500, 400, &lo, &hi);
	ASSERT_EQ(lo, 3500);
	ASSERT_EQ(hi, 4496);
	ASSERT_EQ(puppyarm_align_tick_to_interval(100, lo, hi), 4196);
	ASSERT_EQ(puppyarm_align_tick_to_interval(3600, lo, hi), 3600);
	ASSERT_EQ(puppyarm_align_tick_to_reference(100, 4200.0f), 4196);
}

TEST(puppyarm_default_profile_maps_reference_ticks) {
	puppyarm_profile_t profile;
	puppyarm_profile_get_default(&profile);

	ASSERT_EQ(puppyarm_angle_to_tick(&profile.joints[PUPPYARM_JOINT_YAW],
	                                 0.0f),
	          -1400);
	ASSERT_EQ(puppyarm_angle_to_tick(&profile.joints[PUPPYARM_JOINT_SHOULDER],
	                                 PUPPYARM_PI / 2.0f),
	          530);
	EXPECT_APPROX_EQ(
	    puppyarm_tick_to_angle(&profile.joints[PUPPYARM_JOINT_ELBOW], 3565),
	    0.0f, 0.001f);
	ASSERT_EQ(puppyarm_angle_to_tick(&profile.joints[PUPPYARM_JOINT_TIP],
	                                 PUPPYARM_PI / 2.0f),
	          2807);
}

TEST(puppyarm_fk_straight_pose_matches_link_extent) {
	puppyarm_profile_t profile;
	make_simple_profile(&profile);

	float x = 0.0f;
	float y = 0.0f;
	float z = 0.0f;
	puppyarm_fk(&profile, 0.0f, 0.0f, 0.0f, 0.0f, &x, &y, &z);

	EXPECT_APPROX_EQ(x, -250.0f, 0.001f);
	EXPECT_APPROX_EQ(y, 0.0f, 0.001f);
	EXPECT_APPROX_EQ(z, 0.0f, 0.001f);
}

TEST(puppyarm_fk_tip_down_pose_adds_tool_height_in_z) {
	puppyarm_profile_t profile;
	make_simple_profile(&profile);

	float x = 0.0f;
	float y = 0.0f;
	float z = 0.0f;
	puppyarm_fk(&profile, 0.0f, 0.0f, 0.0f, PUPPYARM_PI / 2.0f, &x, &y,
	            &z);

	EXPECT_APPROX_EQ(x, -200.0f, 0.001f);
	EXPECT_APPROX_EQ(y, 0.0f, 0.001f);
	EXPECT_APPROX_EQ(z, -50.0f, 0.001f);
}

TEST(puppyarm_ik_reachability_matches_basic_roboband_cases) {
	puppyarm_profile_t profile;
	make_simple_profile(&profile);

	puppyarm_ik_result_t max =
	    puppyarm_ik(&profile, 200.0f, 0.0f, -50.0f);
	ASSERT(max.reachable);

	puppyarm_ik_result_t beyond =
	    puppyarm_ik(&profile, 210.0f, 0.0f, -50.0f);
	ASSERT(!beyond.reachable);

	puppyarm_ik_result_t inside =
	    puppyarm_ik(&profile, 20.0f, 0.0f, -50.0f);
	ASSERT(inside.reachable);
}

TEST(puppyarm_ik_known_angles_match_roboband_yaw_convention) {
	puppyarm_profile_t profile;
	make_simple_profile(&profile);

	puppyarm_ik_result_t x =
	    puppyarm_ik(&profile, 200.0f, 0.0f, -50.0f);
	EXPECT_APPROX_EQ(x.yaw, PUPPYARM_PI, 0.001f);
	EXPECT_APPROX_EQ(x.shoulder, 0.0f, 0.001f);
	EXPECT_APPROX_EQ(x.elbow, 0.0f, 0.001f);

	puppyarm_ik_result_t y =
	    puppyarm_ik(&profile, 0.0f, 200.0f, -50.0f);
	EXPECT_APPROX_EQ(y.yaw, PUPPYARM_PI / 2.0f, 0.001f);

	puppyarm_ik_result_t neg_y =
	    puppyarm_ik(&profile, 0.0f, -200.0f, -50.0f);
	EXPECT_APPROX_EQ(neg_y.yaw, -PUPPYARM_PI / 2.0f, 0.001f);
}

TEST(puppyarm_ik_fk_round_trips_reachable_targets) {
	puppyarm_profile_t profile;
	make_simple_profile(&profile);
	const float targets[][3] = {
	    {200.0f, 0.0f, -50.0f},
	    {120.0f, 80.0f, -20.0f},
	    {-80.0f, 120.0f, -40.0f},
	    {0.0f, 100.0f, 40.0f},
	};

	for (int i = 0; i < 4; ++i) {
		puppyarm_ik_result_t ik =
		    puppyarm_ik(&profile, targets[i][0], targets[i][1], targets[i][2]);
		ASSERT(ik.reachable);
		float x = 0.0f;
		float y = 0.0f;
		float z = 0.0f;
		puppyarm_fk(&profile, ik.yaw, ik.shoulder, ik.elbow, ik.tip, &x, &y,
		            &z);
		EXPECT_APPROX_EQ(x, targets[i][0], 0.05f);
		EXPECT_APPROX_EQ(y, targets[i][1], 0.05f);
		EXPECT_APPROX_EQ(z, targets[i][2], 0.05f);
	}
}

TEST(puppyarm_solve_coords_exact_rejects_limit_filtered_targets) {
	puppyarm_profile_t profile;
	make_simple_profile(&profile);
	profile.joints[PUPPYARM_JOINT_YAW].tick_min = 1800;
	profile.joints[PUPPYARM_JOINT_YAW].tick_max = 2200;
	float angles[PUPPYARM_JOINT_COUNT] = {0};
	ASSERT(puppyarm_solve_coords_exact(&profile, 0.0f, 200.0f, -50.0f,
	                                   angles) != 0);
}

TEST(puppyarm_angle_tick_mapping_ignores_soft_limit_changes) {
	puppyarm_profile_t profile;
	make_simple_profile(&profile);
	int32_t before = puppyarm_angle_to_tick(&profile.joints[0], 0.5f);
	float angle_before = puppyarm_tick_to_angle(&profile.joints[0], before);
	profile.joints[0].tick_min = 1000;
	profile.joints[0].tick_max = 1200;
	ASSERT_EQ(puppyarm_angle_to_tick(&profile.joints[0], 0.5f), before);
	EXPECT_APPROX_EQ(puppyarm_tick_to_angle(&profile.joints[0], before),
	                 angle_before, 0.0001f);
}

TEST(puppyarm_controller_init_enables_wheel_mode_and_hard_stops) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);

	ASSERT_EQ(fake.wheel_mode_calls, PUPPYARM_JOINT_COUNT);
	ASSERT_EQ(fake.speed_calls, PUPPYARM_JOINT_COUNT);
	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i)
		ASSERT_EQ(fake.speed[i], 0);
}

TEST(puppyarm_controller_init_records_wheel_mode_failure) {
	puppyarm_profile_t profile;
	make_simple_profile(&profile);
	fake_arm_bus_t fake;
	memset(&fake, 0, sizeof(fake));
	fake.wheel_mode_rc = -7;
	puppyarm_bus_t bus = make_fake_bus(&fake);
	puppyarm_controller_t ctrl;
	ASSERT_EQ(puppyarm_controller_init(&ctrl, &profile, &bus, 0), 0);
	ASSERT_EQ(puppyarm_controller_start(&ctrl, 0), -7);
	ASSERT(ctrl.joints[0].fault[0] != '\0');
}

TEST(puppyarm_controller_tracks_target_ticks) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	ASSERT_EQ(fake.wheel_mode_calls, PUPPYARM_JOINT_COUNT);

	int32_t ticks[PUPPYARM_JOINT_COUNT] = {100, 100, 100, 100};
	ASSERT_EQ(puppyarm_controller_goto_ticks(&ctrl, ticks, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT(fake.speed[0] > 0);
	ASSERT(fake.speed[1] > 0);

	for (int i = 0; i < PUPPYARM_JOINT_COUNT; ++i)
		fake.pos[i] = 100;
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 20), 0);
	ASSERT_EQ(fake.speed[0], 0);
	ASSERT_EQ(fake.speed[1], 0);
}

TEST(puppyarm_controller_target_deadband_stops_without_motion) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	set_all_positions(&fake, 100);

	int32_t ticks[PUPPYARM_JOINT_COUNT] = {105, 105, 105, 105};
	ASSERT_EQ(puppyarm_controller_goto_ticks(&ctrl, ticks, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT_EQ(fake.speed[0], 0);
	ASSERT(!any_target_set(&ctrl));
}

TEST(puppyarm_controller_reduces_speed_near_target) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	set_all_positions(&fake, 60);

	int32_t ticks[PUPPYARM_JOINT_COUNT] = {100, 100, 100, 100};
	ASSERT_EQ(puppyarm_controller_goto_ticks(&ctrl, ticks, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT_EQ(fake.speed[0], 100);
}

TEST(puppyarm_controller_changes_direction_for_negative_error) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	set_all_positions(&fake, 200);

	int32_t ticks[PUPPYARM_JOINT_COUNT] = {100, 100, 100, 100};
	ASSERT_EQ(puppyarm_controller_goto_ticks(&ctrl, ticks, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT(fake.speed[0] < 0);
}

TEST(puppyarm_controller_stop_cancels_active_target) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);

	int32_t ticks[PUPPYARM_JOINT_COUNT] = {100, 100, 100, 100};
	ASSERT_EQ(puppyarm_controller_goto_ticks(&ctrl, ticks, 200, 1), 0);
	ASSERT(any_target_set(&ctrl));
	puppyarm_controller_stop_all(&ctrl, 2);
	ASSERT(!any_target_set(&ctrl));
	ASSERT_EQ(fake.speed[0], 0);
}

TEST(puppyarm_controller_goto_angles_sets_target_ticks) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);

	float angles[PUPPYARM_JOINT_COUNT] = {0.1f, 0.2f, -0.1f, 0.0f};
	ASSERT_EQ(puppyarm_controller_goto_angles(&ctrl, angles, 200, 1), 0);
	ASSERT(any_target_set(&ctrl));
	ASSERT_EQ(ctrl.joints[0].target_tick,
	          puppyarm_angle_to_tick(&profile.joints[0], angles[0]));
}

TEST(puppyarm_controller_goto_coords_uses_ik) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);

	ASSERT_EQ(puppyarm_controller_goto_coords(&ctrl, 200.0f, 0.0f, -50.0f,
	                                          200, 1),
	          0);
	ASSERT(any_target_set(&ctrl));
}

TEST(puppyarm_controller_goto_coords_rejects_unreachable_target) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);

	ASSERT(puppyarm_controller_goto_coords(&ctrl, 500.0f, 0.0f, -50.0f, 200,
	                                       1) != 0);
	ASSERT(!any_target_set(&ctrl));
	ASSERT(ctrl.last_error[0] != '\0');
}

TEST(puppyarm_controller_limit_blocks_motion_deeper_outside) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	profile.joints[0].tick_min = 0;
	ctrl.profile.joints[0].tick_min = 0;
	profile.joints[0].tick_max = 100;
	ctrl.profile.joints[0].tick_max = 100;
	fake.pos[0] = 100;

	ASSERT_EQ(puppyarm_controller_jog(&ctrl, 0, 1, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT_EQ(fake.speed[0], 0);
	ASSERT(ctrl.joints[0].fault[0] != '\0');
}

TEST(puppyarm_controller_allows_return_within_limits) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	ctrl.profile.joints[0].tick_min = 0;
	ctrl.profile.joints[0].tick_max = 100;
	fake.pos[0] = 100;

	int32_t ticks[PUPPYARM_JOINT_COUNT] = {50, 0, 0, 0};
	ASSERT_EQ(puppyarm_controller_goto_ticks(&ctrl, ticks, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT(fake.speed[0] < 0);
}

TEST(puppyarm_controller_limits_disabled_allow_target_motion) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	ctrl.profile.joints[0].limit_enabled = false;
	ctrl.profile.joints[0].tick_min = 0;
	ctrl.profile.joints[0].tick_max = 100;
	fake.pos[0] = 100;

	int32_t ticks[PUPPYARM_JOINT_COUNT] = {200, 0, 0, 0};
	ASSERT_EQ(puppyarm_controller_goto_ticks(&ctrl, ticks, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT(fake.speed[0] > 0);
}

TEST(puppyarm_controller_read_failure_with_active_target_stops_motion) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	int32_t ticks[PUPPYARM_JOINT_COUNT] = {100, 100, 100, 100};
	ASSERT_EQ(puppyarm_controller_goto_ticks(&ctrl, ticks, 200, 1), 0);
	fake.read_rc = -1;
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT_EQ(fake.speed[0], 0);
	ASSERT(ctrl.joints[0].fault[0] != '\0');
}

TEST(puppyarm_controller_deadman_stops_stale_jog) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	ASSERT_EQ(puppyarm_controller_jog(&ctrl, 0, 1, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT(fake.speed[0] > 0);

	ASSERT(puppyarm_controller_step(&ctrl, 2000) != 0);
	ASSERT_EQ(fake.speed[0], 0);
}

TEST(puppyarm_controller_command_deadman_does_not_cancel_target_tracking) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	int32_t ticks[PUPPYARM_JOINT_COUNT] = {500, 500, 500, 500};
	ASSERT_EQ(puppyarm_controller_goto_ticks(&ctrl, ticks, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 2000), 0);
	ASSERT(any_target_set(&ctrl));
	ASSERT(fake.speed[0] > 0);
}

TEST(puppyarm_controller_feedback_deadman_stops_after_all_reads_fail) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	ASSERT_EQ(puppyarm_controller_jog(&ctrl, 0, 1, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	fake.read_rc = -1;
	ASSERT(puppyarm_controller_step(&ctrl, 400) != 0);
	ASSERT_EQ(fake.speed[0], 0);
	ASSERT(ctrl.last_error[0] != '\0');
}

TEST(puppyarm_controller_set_speed_zero_stops_spin_and_goto) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	ASSERT_EQ(puppyarm_controller_jog(&ctrl, 0, 1, 200, 1), 0);
	ASSERT_EQ(puppyarm_controller_set_speed(&ctrl, 0), 0);
	ASSERT_EQ(fake.speed[0], 0);

	int32_t ticks[PUPPYARM_JOINT_COUNT] = {500, 500, 500, 500};
	ASSERT_EQ(puppyarm_controller_goto_ticks(&ctrl, ticks, 200, 2), 0);
	ASSERT(any_target_set(&ctrl));
	ASSERT_EQ(puppyarm_controller_set_speed(&ctrl, 0), 0);
	ASSERT(!any_target_set(&ctrl));
}

TEST(puppyarm_controller_set_speed_increase_updates_active_spin) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	set_all_positions(&fake, 2000);
	ASSERT_EQ(puppyarm_controller_jog(&ctrl, 0, -1, 100, 1), 0);
	ASSERT_EQ(puppyarm_controller_set_speed(&ctrl, 250), 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT_EQ(fake.speed[0], -250);
}

TEST(puppyarm_controller_clear_faults_clears_latched_faults) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	ctrl.joints[0].fault[0] = 'x';
	ctrl.joints[0].fault[1] = '\0';
	ctrl.last_error[0] = 'y';
	ctrl.last_error[1] = '\0';
	puppyarm_controller_clear_faults(&ctrl);
	ASSERT_EQ(ctrl.joints[0].fault[0], '\0');
	ASSERT_EQ(ctrl.last_error[0], '\0');
}

TEST(puppyarm_controller_invalid_commands_return_errors) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	ASSERT(puppyarm_controller_jog(&ctrl, PUPPYARM_JOINT_COUNT, 1, 100, 1) !=
	       0);
	ASSERT(puppyarm_controller_goto_ticks(NULL, NULL, 0, 0) != 0);
	ASSERT(puppyarm_controller_goto_angles(&ctrl, NULL, 0, 0) != 0);
}

TEST(puppyarm_controller_current_angles_require_feedback) {
	puppyarm_controller_t ctrl;
	puppyarm_profile_t profile;
	fake_arm_bus_t fake;
	make_started_controller(&ctrl, &profile, &fake);
	float angles[PUPPYARM_JOINT_COUNT] = {0};
	ASSERT(puppyarm_controller_current_angles(&ctrl, angles) != 0);
	ASSERT_EQ(puppyarm_controller_step(&ctrl, 10), 0);
	ASSERT_EQ(puppyarm_controller_current_angles(&ctrl, angles), 0);
}
