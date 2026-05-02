#ifndef PROTOCOL_H
#define PROTOCOL_H

#include "test.h"
#include <stdint.h>
#include <string.h>

#define CMD_PING 1
#define CMD_DRIVE_MOTOR 2
#define CMD_STOP_MOTOR 3
#define CMD_STOP_ALL_MOTORS 4
#define CMD_APPLY_CONFIG 6
#define CMD_SMARTBUS_SCAN 7
#define CMD_SMARTBUS_SET_ID 8
#define CMD_SET_MOTOR_POLL 9
#define CMD_SET_BOT_ID 10
#define CMD_ARM_MOVE 11
#define CMD_ARM_SET_SPEED 12
#define CMD_ARM_JOG 13
#define CMD_ARM_STOP_JOINT 14
#define CMD_ARM_STOP_ALL 15
#define CMD_ARM_GOTO_TICKS 16
#define CMD_ARM_GOTO_ANGLES 17
#define CMD_ARM_GOTO_COORDS 18
#define CMD_ARM_HOLD 19
#define CMD_ARM_SET_JOINT_TICK 20
#define CMD_ARM_SET_TICK_LIMITS 21
#define CMD_ARM_SET_TICK_LIMITS_ENABLED 22
#define CMD_ARM_MOVE_RELATIVE 23
#define CMD_ARM_CLEAR_FAULTS 24

#define MSG_TO_SRV_PONG 0x01
#define MSG_TO_SRV_MY_INFO 0x02
#define MSG_TO_SRV_MOTOR_STATE 0x03
#define MSG_TO_SRV_SMARTBUS_SCAN_RESULT 0x04
#define MSG_TO_SRV_SMARTBUS_SET_ID_RESULT 0x05
#define MSG_TO_SRV_CONFIG_BLOB 0x06
#define MSG_TO_SRV_ARM_STATE 0x07

#define PUPPY_PROTOCOL_VERSION 1

enum MotorType {
	DC_MOTOR = 0,
	SERVO_MOTOR = 1,
};

typedef struct {
	int motor_id;
	enum MotorType motor_type;
	int speed;
	int steps;     // For DC pulse counts or servo duration (ms) when
	               // motor_type=SERVO_MOTOR
	int step_time; // Microseconds per step when motor_type=DC_MOTOR
	int angle;
} DriveMotorCommand;

typedef struct {
	int uart_port;
	int start_id;
	int end_id;
} SmartbusScanCommand;

typedef struct {
	int uart_port;
	int old_id;
	int new_id;
} SmartbusSetIdCommand;

typedef struct {
	int count;
	uint8_t ids[32];
} MotorPollCommand;

typedef struct {
	int motor_id;
} StopMotorCommand;

typedef struct {
	float x;
	float y;
	float z;
	uint8_t elbow_up;
	uint16_t duration_ms;
} ArmMoveCommand;

typedef struct {
	uint16_t speed;
} ArmSetSpeedCommand;

typedef struct {
	uint8_t joint;
	int8_t direction;
	uint16_t speed;
} ArmJogCommand;

typedef struct {
	uint8_t joint;
} ArmJointCommand;

typedef struct {
	uint16_t speed;
	int32_t ticks[4];
} ArmGotoTicksCommand;

typedef struct {
	uint16_t speed;
	float angles_deg[4];
} ArmGotoAnglesCommand;

typedef struct {
	uint16_t speed;
	float x;
	float y;
	float z;
} ArmGotoCoordsCommand;

typedef struct {
	uint8_t joint;
	uint16_t speed;
	int32_t tick;
} ArmSetJointTickCommand;

typedef struct {
	uint8_t joint;
	int32_t min_tick;
	int32_t max_tick;
} ArmSetTickLimitsCommand;

typedef struct {
	uint8_t joint;
	uint8_t enabled;
} ArmSetTickLimitsEnabledCommand;

typedef struct {
	uint16_t speed;
	float dx;
	float dy;
} ArmMoveRelativeCommand;

typedef struct {
	const uint8_t *data;
	uint16_t length;
} SetBotIdCommand;

union Command {
	DriveMotorCommand drive_motor;
	StopMotorCommand stop_motor;
	SmartbusScanCommand smartbus_scan;
	SmartbusSetIdCommand smartbus_set_id;
	MotorPollCommand motor_poll;
	struct {
		const uint8_t *data;
		uint16_t length;
	} apply_config;
	ArmMoveCommand arm_move;
	ArmSetSpeedCommand arm_set_speed;
	ArmJogCommand arm_jog;
	ArmJointCommand arm_joint;
	ArmGotoTicksCommand arm_goto_ticks;
	ArmGotoAnglesCommand arm_goto_angles;
	ArmGotoCoordsCommand arm_goto_coords;
	ArmSetJointTickCommand arm_set_joint_tick;
	ArmSetTickLimitsCommand arm_set_tick_limits;
	ArmSetTickLimitsEnabledCommand arm_set_tick_limits_enabled;
	ArmMoveRelativeCommand arm_move_relative;
	SetBotIdCommand set_bot_id;
};

typedef struct {
	int cmd_type;
	union Command cmd;
} CommandPacket;

static inline const char *command_type_to_string(int cmd_type) {
	switch (cmd_type) {
	case CMD_PING:
		return "PING";
	case CMD_DRIVE_MOTOR:
		return "DRIVE_MOTOR";
	case CMD_STOP_MOTOR:
		return "STOP_MOTOR";
	case CMD_STOP_ALL_MOTORS:
		return "STOP_ALL_MOTORS";
	case CMD_APPLY_CONFIG:
		return "APPLY_CONFIG";
	case CMD_SMARTBUS_SCAN:
		return "SMARTBUS_SCAN";
	case CMD_SMARTBUS_SET_ID:
		return "SMARTBUS_SET_ID";
	case CMD_SET_MOTOR_POLL:
		return "SET_MOTOR_POLL";
	case CMD_SET_BOT_ID:
		return "SET_BOT_ID";
	case CMD_ARM_MOVE:
		return "ARM_MOVE";
	case CMD_ARM_SET_SPEED:
		return "ARM_SET_SPEED";
	case CMD_ARM_JOG:
		return "ARM_JOG";
	case CMD_ARM_STOP_JOINT:
		return "ARM_STOP_JOINT";
	case CMD_ARM_STOP_ALL:
		return "ARM_STOP_ALL";
	case CMD_ARM_GOTO_TICKS:
		return "ARM_GOTO_TICKS";
	case CMD_ARM_GOTO_ANGLES:
		return "ARM_GOTO_ANGLES";
	case CMD_ARM_GOTO_COORDS:
		return "ARM_GOTO_COORDS";
	case CMD_ARM_HOLD:
		return "ARM_HOLD";
	case CMD_ARM_SET_JOINT_TICK:
		return "ARM_SET_JOINT_TICK";
	case CMD_ARM_SET_TICK_LIMITS:
		return "ARM_SET_TICK_LIMITS";
	case CMD_ARM_SET_TICK_LIMITS_ENABLED:
		return "ARM_SET_TICK_LIMITS_ENABLED";
	case CMD_ARM_MOVE_RELATIVE:
		return "ARM_MOVE_RELATIVE";
	case CMD_ARM_CLEAR_FAULTS:
		return "ARM_CLEAR_FAULTS";
	default:
		return "UNKNOWN";
	}
}

static inline uint16_t protocol_read_u16_le(const uint8_t *payload) {
	return (uint16_t)(payload[0] | (payload[1] << 8));
}

static inline int32_t protocol_read_i32_le(const uint8_t *payload) {
	uint32_t raw = (uint32_t)payload[0] | ((uint32_t)payload[1] << 8) |
	               ((uint32_t)payload[2] << 16) | ((uint32_t)payload[3] << 24);
	return (int32_t)raw;
}

static inline float protocol_read_float_le(const uint8_t *payload) {
	uint32_t raw = (uint32_t)payload[0] | ((uint32_t)payload[1] << 8) |
	               ((uint32_t)payload[2] << 16) | ((uint32_t)payload[3] << 24);
	float value = 0.0f;
	memcpy(&value, &raw, sizeof(value));
	return value;
}

static inline void parse_cmd(uint8_t *data, CommandPacket *cmd_packet) {
	int version = data[0];
	int cmd_type = data[1];
	(void)version;
	int payload_len = data[2] | (data[3] << 8);
	uint8_t *payload = &data[4];

	switch (cmd_type) {
	case CMD_PING:
		cmd_packet->cmd_type = CMD_PING;
		break;
	case CMD_DRIVE_MOTOR:
		cmd_packet->cmd_type = CMD_DRIVE_MOTOR;
		cmd_packet->cmd.drive_motor.motor_id =
		    (payload_len >= 1) ? payload[0] : 0;
		cmd_packet->cmd.drive_motor.motor_type =
		    (payload_len >= 2) ? (enum MotorType)payload[1] : DC_MOTOR;
		cmd_packet->cmd.drive_motor.speed =
		    (payload_len >= 3) ? (int8_t)payload[2] : 0;
		cmd_packet->cmd.drive_motor.steps =
		    (payload_len >= 5) ? (int16_t)(payload[3] | (payload[4] << 8)) : 0;
		cmd_packet->cmd.drive_motor.step_time =
		    (payload_len >= 7) ? (int16_t)(payload[5] | (payload[6] << 8)) : 0;
		cmd_packet->cmd.drive_motor.angle =
		    (payload_len >= 9) ? (int16_t)(payload[7] | (payload[8] << 8)) : 0;
		break;
	case CMD_STOP_MOTOR:
		cmd_packet->cmd_type = CMD_STOP_MOTOR;
		cmd_packet->cmd.stop_motor.motor_id = payload[0];
		break;
	case CMD_STOP_ALL_MOTORS:
		cmd_packet->cmd_type = CMD_STOP_ALL_MOTORS;
		break;
	case CMD_APPLY_CONFIG:
		cmd_packet->cmd_type = CMD_APPLY_CONFIG;
		cmd_packet->cmd.apply_config.data = payload;
		cmd_packet->cmd.apply_config.length = (uint16_t)payload_len;
		break;
	case CMD_SMARTBUS_SCAN:
		cmd_packet->cmd_type = CMD_SMARTBUS_SCAN;
		cmd_packet->cmd.smartbus_scan.uart_port =
		    (payload_len >= 1) ? payload[0] : 0;
		cmd_packet->cmd.smartbus_scan.start_id =
		    (payload_len >= 2) ? payload[1] : 1;
		cmd_packet->cmd.smartbus_scan.end_id =
		    (payload_len >= 3) ? payload[2] : 253;
		break;
	case CMD_SMARTBUS_SET_ID:
		cmd_packet->cmd_type = CMD_SMARTBUS_SET_ID;
		cmd_packet->cmd.smartbus_set_id.uart_port =
		    (payload_len >= 1) ? payload[0] : 0;
		cmd_packet->cmd.smartbus_set_id.old_id =
		    (payload_len >= 2) ? payload[1] : 0;
		cmd_packet->cmd.smartbus_set_id.new_id =
		    (payload_len >= 3) ? payload[2] : 0;
		break;
	case CMD_SET_MOTOR_POLL: {
		cmd_packet->cmd_type = CMD_SET_MOTOR_POLL;
		uint8_t count = (payload_len >= 1) ? payload[0] : 0;
		if (count > 32)
			count = 32;
		cmd_packet->cmd.motor_poll.count = (int)count;
		for (uint8_t i = 0; i < count; ++i) {
			cmd_packet->cmd.motor_poll.ids[i] =
			    (payload_len >= (int)(2 + i)) ? payload[1 + i] : 0;
		}
	} break;
	case CMD_SET_BOT_ID:
		cmd_packet->cmd_type = CMD_SET_BOT_ID;
		cmd_packet->cmd.set_bot_id.data = payload;
		cmd_packet->cmd.set_bot_id.length = (uint16_t)payload_len;
		break;
	case CMD_ARM_MOVE:
		cmd_packet->cmd_type = CMD_ARM_MOVE;
		cmd_packet->cmd.arm_move.x =
		    (payload_len >= 4) ? protocol_read_float_le(payload) : 0.0f;
		cmd_packet->cmd.arm_move.y =
		    (payload_len >= 8) ? protocol_read_float_le(payload + 4) : 0.0f;
		cmd_packet->cmd.arm_move.z =
		    (payload_len >= 12) ? protocol_read_float_le(payload + 8) : 0.0f;
		cmd_packet->cmd.arm_move.elbow_up =
		    (payload_len >= 13) ? payload[12] : 0;
		cmd_packet->cmd.arm_move.duration_ms =
		    (payload_len >= 15) ? (uint16_t)(payload[13] | (payload[14] << 8)) : 0;
		break;
	case CMD_ARM_SET_SPEED:
		cmd_packet->cmd_type = CMD_ARM_SET_SPEED;
		cmd_packet->cmd.arm_set_speed.speed =
		    (payload_len >= 2) ? protocol_read_u16_le(payload) : 0;
		break;
	case CMD_ARM_JOG:
		cmd_packet->cmd_type = CMD_ARM_JOG;
		cmd_packet->cmd.arm_jog.joint = (payload_len >= 1) ? payload[0] : 0;
		cmd_packet->cmd.arm_jog.direction =
		    (payload_len >= 2) ? (int8_t)payload[1] : 0;
		cmd_packet->cmd.arm_jog.speed =
		    (payload_len >= 4) ? protocol_read_u16_le(payload + 2) : 0;
		break;
	case CMD_ARM_STOP_JOINT:
		cmd_packet->cmd_type = CMD_ARM_STOP_JOINT;
		cmd_packet->cmd.arm_joint.joint = (payload_len >= 1) ? payload[0] : 0;
		break;
	case CMD_ARM_STOP_ALL:
		cmd_packet->cmd_type = CMD_ARM_STOP_ALL;
		break;
	case CMD_ARM_GOTO_TICKS:
		cmd_packet->cmd_type = CMD_ARM_GOTO_TICKS;
		cmd_packet->cmd.arm_goto_ticks.speed =
		    (payload_len >= 2) ? protocol_read_u16_le(payload) : 0;
		for (uint8_t i = 0; i < 4; ++i) {
			cmd_packet->cmd.arm_goto_ticks.ticks[i] =
			    (payload_len >= (int)(6 + i * 4))
			        ? protocol_read_i32_le(payload + 2 + i * 4)
			        : 0;
		}
		break;
	case CMD_ARM_GOTO_ANGLES:
		cmd_packet->cmd_type = CMD_ARM_GOTO_ANGLES;
		cmd_packet->cmd.arm_goto_angles.speed =
		    (payload_len >= 2) ? protocol_read_u16_le(payload) : 0;
		for (uint8_t i = 0; i < 4; ++i) {
			cmd_packet->cmd.arm_goto_angles.angles_deg[i] =
			    (payload_len >= (int)(6 + i * 4))
			        ? protocol_read_float_le(payload + 2 + i * 4)
			        : 0.0f;
		}
		break;
	case CMD_ARM_GOTO_COORDS:
		cmd_packet->cmd_type = CMD_ARM_GOTO_COORDS;
		cmd_packet->cmd.arm_goto_coords.speed =
		    (payload_len >= 2) ? protocol_read_u16_le(payload) : 0;
		cmd_packet->cmd.arm_goto_coords.x =
		    (payload_len >= 6) ? protocol_read_float_le(payload + 2) : 0.0f;
		cmd_packet->cmd.arm_goto_coords.y =
		    (payload_len >= 10) ? protocol_read_float_le(payload + 6) : 0.0f;
		cmd_packet->cmd.arm_goto_coords.z =
		    (payload_len >= 14) ? protocol_read_float_le(payload + 10) : 0.0f;
		break;
	case CMD_ARM_HOLD:
		cmd_packet->cmd_type = CMD_ARM_HOLD;
		cmd_packet->cmd.arm_set_speed.speed =
		    (payload_len >= 2) ? protocol_read_u16_le(payload) : 0;
		break;
	case CMD_ARM_SET_JOINT_TICK:
		cmd_packet->cmd_type = CMD_ARM_SET_JOINT_TICK;
		cmd_packet->cmd.arm_set_joint_tick.joint =
		    (payload_len >= 1) ? payload[0] : 0;
		cmd_packet->cmd.arm_set_joint_tick.speed =
		    (payload_len >= 3) ? protocol_read_u16_le(payload + 1) : 0;
		cmd_packet->cmd.arm_set_joint_tick.tick =
		    (payload_len >= 7) ? protocol_read_i32_le(payload + 3) : 0;
		break;
	case CMD_ARM_SET_TICK_LIMITS:
		cmd_packet->cmd_type = CMD_ARM_SET_TICK_LIMITS;
		cmd_packet->cmd.arm_set_tick_limits.joint =
		    (payload_len >= 1) ? payload[0] : 0;
		cmd_packet->cmd.arm_set_tick_limits.min_tick =
		    (payload_len >= 5) ? protocol_read_i32_le(payload + 1) : 0;
		cmd_packet->cmd.arm_set_tick_limits.max_tick =
		    (payload_len >= 9) ? protocol_read_i32_le(payload + 5) : 0;
		break;
	case CMD_ARM_SET_TICK_LIMITS_ENABLED:
		cmd_packet->cmd_type = CMD_ARM_SET_TICK_LIMITS_ENABLED;
		cmd_packet->cmd.arm_set_tick_limits_enabled.joint =
		    (payload_len >= 1) ? payload[0] : 0;
		cmd_packet->cmd.arm_set_tick_limits_enabled.enabled =
		    (payload_len >= 2) ? payload[1] : 0;
		break;
	case CMD_ARM_MOVE_RELATIVE:
		cmd_packet->cmd_type = CMD_ARM_MOVE_RELATIVE;
		cmd_packet->cmd.arm_move_relative.speed =
		    (payload_len >= 2) ? protocol_read_u16_le(payload) : 0;
		cmd_packet->cmd.arm_move_relative.dx =
		    (payload_len >= 6) ? protocol_read_float_le(payload + 2) : 0.0f;
		cmd_packet->cmd.arm_move_relative.dy =
		    (payload_len >= 10) ? protocol_read_float_le(payload + 6) : 0.0f;
		break;
	case CMD_ARM_CLEAR_FAULTS:
		cmd_packet->cmd_type = CMD_ARM_CLEAR_FAULTS;
		cmd_packet->cmd.arm_joint.joint = (payload_len >= 1) ? payload[0] : 255;
		break;
	default:
		break;
	}
}

static inline void protocol_test_write_u16_le(uint8_t *dst, uint16_t value) {
	dst[0] = (uint8_t)(value & 0xff);
	dst[1] = (uint8_t)((value >> 8) & 0xff);
}

static inline void protocol_test_write_i32_le(uint8_t *dst, int32_t value) {
	uint32_t raw = (uint32_t)value;
	dst[0] = (uint8_t)(raw & 0xff);
	dst[1] = (uint8_t)((raw >> 8) & 0xff);
	dst[2] = (uint8_t)((raw >> 16) & 0xff);
	dst[3] = (uint8_t)((raw >> 24) & 0xff);
}

static inline void protocol_test_write_float_le(uint8_t *dst, float value) {
	memcpy(dst, &value, sizeof(value));
}

TEST(parse_cmd_test) {
	uint8_t data[] = {
	    0x01,            // version
	    CMD_DRIVE_MOTOR, // command
	    0x09, 0x00,      // payload length = 9 (LE)

	    // Payload (9 bytes):
	    0x01,       // motor_id
	    0x00,       // motor_type (DC_MOTOR)
	    0x02,       // speed
	    0x03, 0x00, // steps = 3
	    0x05, 0x00, // step_time = 5
	    0x07, 0x00  // angle = 7
	};

	CommandPacket cmd_packet;
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_DRIVE_MOTOR);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.motor_id, 1);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.motor_type, DC_MOTOR);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.speed, 2);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.steps, 3);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.step_time, 5);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.angle, 7);
}

TEST(parse_arm_move_cmd_test) {
	uint8_t data[4 + 15] = {0};
	data[0] = 0x01;
	data[1] = CMD_ARM_MOVE;
	data[2] = 0x0f;
	data[3] = 0x00;
	float x = 1.0f;
	float y = 2.0f;
	float z = 3.5f;
	memcpy(&data[4], &x, sizeof(x));
	memcpy(&data[8], &y, sizeof(y));
	memcpy(&data[12], &z, sizeof(z));
	data[16] = 1;
	data[17] = 0xf4;
	data[18] = 0x01;

	CommandPacket cmd_packet;
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_MOVE);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_move.x, 1.0f, 0.0001f);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_move.y, 2.0f, 0.0001f);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_move.z, 3.5f, 0.0001f);
	ASSERT_EQ(cmd_packet.cmd.arm_move.elbow_up, 1);
	ASSERT_EQ(cmd_packet.cmd.arm_move.duration_ms, 500);
}

TEST(parse_apply_config_test) {
	uint8_t blob[] = {0x01, // version
	                  CMD_APPLY_CONFIG,
	                  0x04,
	                  0x00, // payload length = 4
	                  0xAA,
	                  0xBB,
	                  0xCC,
	                  0xDD};

	CommandPacket cmd_packet;
	parse_cmd(blob, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_APPLY_CONFIG);
	ASSERT_EQ(cmd_packet.cmd.apply_config.length, 4u);
	ASSERT(cmd_packet.cmd.apply_config.data != NULL);
	ASSERT_EQ(cmd_packet.cmd.apply_config.data[0], 0xAA);
	ASSERT_EQ(cmd_packet.cmd.apply_config.data[3], 0xDD);
}

TEST(parse_arm_set_speed_cmd_test) {
	uint8_t data[4 + 2] = {0x01, CMD_ARM_SET_SPEED, 0x02, 0x00};
	protocol_test_write_u16_le(&data[4], 250);

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_SET_SPEED);
	ASSERT_EQ(cmd_packet.cmd.arm_set_speed.speed, 250);
}

TEST(parse_arm_jog_cmd_test) {
	uint8_t data[4 + 4] = {0x01, CMD_ARM_JOG, 0x04, 0x00};
	data[4] = 2;
	data[5] = (uint8_t)-1;
	protocol_test_write_u16_le(&data[6], 300);

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_JOG);
	ASSERT_EQ(cmd_packet.cmd.arm_jog.joint, 2);
	ASSERT_EQ(cmd_packet.cmd.arm_jog.direction, -1);
	ASSERT_EQ(cmd_packet.cmd.arm_jog.speed, 300);
}

TEST(parse_arm_stop_cmds_test) {
	uint8_t stop_joint[4 + 1] = {0x01, CMD_ARM_STOP_JOINT, 0x01, 0x00, 3};
	uint8_t stop_all[4] = {0x01, CMD_ARM_STOP_ALL, 0x00, 0x00};

	CommandPacket cmd_packet = {0};
	parse_cmd(stop_joint, &cmd_packet);
	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_STOP_JOINT);
	ASSERT_EQ(cmd_packet.cmd.arm_joint.joint, 3);

	parse_cmd(stop_all, &cmd_packet);
	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_STOP_ALL);
}

TEST(parse_arm_goto_ticks_cmd_test) {
	uint8_t data[4 + 18] = {0x01, CMD_ARM_GOTO_TICKS, 0x12, 0x00};
	protocol_test_write_u16_le(&data[4], 400);
	protocol_test_write_i32_le(&data[6], -1400);
	protocol_test_write_i32_le(&data[10], 530);
	protocol_test_write_i32_le(&data[14], 3565);
	protocol_test_write_i32_le(&data[18], 1783);

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_GOTO_TICKS);
	ASSERT_EQ(cmd_packet.cmd.arm_goto_ticks.speed, 400);
	ASSERT_EQ(cmd_packet.cmd.arm_goto_ticks.ticks[0], -1400);
	ASSERT_EQ(cmd_packet.cmd.arm_goto_ticks.ticks[1], 530);
	ASSERT_EQ(cmd_packet.cmd.arm_goto_ticks.ticks[2], 3565);
	ASSERT_EQ(cmd_packet.cmd.arm_goto_ticks.ticks[3], 1783);
}

TEST(parse_arm_goto_angles_cmd_test) {
	uint8_t data[4 + 18] = {0x01, CMD_ARM_GOTO_ANGLES, 0x12, 0x00};
	protocol_test_write_u16_le(&data[4], 500);
	protocol_test_write_float_le(&data[6], 10.0f);
	protocol_test_write_float_le(&data[10], -20.5f);
	protocol_test_write_float_le(&data[14], 30.25f);
	protocol_test_write_float_le(&data[18], 45.0f);

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_GOTO_ANGLES);
	ASSERT_EQ(cmd_packet.cmd.arm_goto_angles.speed, 500);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_goto_angles.angles_deg[0], 10.0f,
	                 0.0001f);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_goto_angles.angles_deg[1], -20.5f,
	                 0.0001f);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_goto_angles.angles_deg[2], 30.25f,
	                 0.0001f);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_goto_angles.angles_deg[3], 45.0f,
	                 0.0001f);
}

TEST(parse_arm_goto_coords_cmd_test) {
	uint8_t data[4 + 14] = {0x01, CMD_ARM_GOTO_COORDS, 0x0e, 0x00};
	protocol_test_write_u16_le(&data[4], 180);
	protocol_test_write_float_le(&data[6], 100.0f);
	protocol_test_write_float_le(&data[10], -25.5f);
	protocol_test_write_float_le(&data[14], 60.0f);

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_GOTO_COORDS);
	ASSERT_EQ(cmd_packet.cmd.arm_goto_coords.speed, 180);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_goto_coords.x, 100.0f, 0.0001f);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_goto_coords.y, -25.5f, 0.0001f);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_goto_coords.z, 60.0f, 0.0001f);
}

TEST(parse_arm_hold_cmd_test) {
	uint8_t data[4 + 2] = {0x01, CMD_ARM_HOLD, 0x02, 0x00};
	protocol_test_write_u16_le(&data[4], 210);

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_HOLD);
	ASSERT_EQ(cmd_packet.cmd.arm_set_speed.speed, 210);
}

TEST(parse_arm_set_joint_tick_cmd_test) {
	uint8_t data[4 + 7] = {0x01, CMD_ARM_SET_JOINT_TICK, 0x07, 0x00};
	data[4] = 1;
	protocol_test_write_u16_le(&data[5], 190);
	protocol_test_write_i32_le(&data[7], -100);

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_SET_JOINT_TICK);
	ASSERT_EQ(cmd_packet.cmd.arm_set_joint_tick.joint, 1);
	ASSERT_EQ(cmd_packet.cmd.arm_set_joint_tick.speed, 190);
	ASSERT_EQ(cmd_packet.cmd.arm_set_joint_tick.tick, -100);
}

TEST(parse_arm_set_tick_limits_cmd_test) {
	uint8_t data[4 + 9] = {0x01, CMD_ARM_SET_TICK_LIMITS, 0x09, 0x00};
	data[4] = 2;
	protocol_test_write_i32_le(&data[5], -300);
	protocol_test_write_i32_le(&data[9], 900);

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_SET_TICK_LIMITS);
	ASSERT_EQ(cmd_packet.cmd.arm_set_tick_limits.joint, 2);
	ASSERT_EQ(cmd_packet.cmd.arm_set_tick_limits.min_tick, -300);
	ASSERT_EQ(cmd_packet.cmd.arm_set_tick_limits.max_tick, 900);
}

TEST(parse_arm_set_tick_limits_enabled_cmd_test) {
	uint8_t data[4 + 2] = {0x01, CMD_ARM_SET_TICK_LIMITS_ENABLED,
	                       0x02, 0x00, 0x03, 0x01};

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_SET_TICK_LIMITS_ENABLED);
	ASSERT_EQ(cmd_packet.cmd.arm_set_tick_limits_enabled.joint, 3);
	ASSERT_EQ(cmd_packet.cmd.arm_set_tick_limits_enabled.enabled, 1);
}

TEST(parse_arm_move_relative_cmd_test) {
	uint8_t data[4 + 10] = {0x01, CMD_ARM_MOVE_RELATIVE, 0x0a, 0x00};
	protocol_test_write_u16_le(&data[4], 160);
	protocol_test_write_float_le(&data[6], 12.5f);
	protocol_test_write_float_le(&data[10], -4.0f);

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_MOVE_RELATIVE);
	ASSERT_EQ(cmd_packet.cmd.arm_move_relative.speed, 160);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_move_relative.dx, 12.5f, 0.0001f);
	EXPECT_APPROX_EQ(cmd_packet.cmd.arm_move_relative.dy, -4.0f, 0.0001f);
}

TEST(parse_arm_clear_faults_cmd_test) {
	uint8_t data[4 + 1] = {0x01, CMD_ARM_CLEAR_FAULTS, 0x01, 0x00, 255};

	CommandPacket cmd_packet = {0};
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_ARM_CLEAR_FAULTS);
	ASSERT_EQ(cmd_packet.cmd.arm_joint.joint, 255);
}

#endif // PROTOCOL_H
