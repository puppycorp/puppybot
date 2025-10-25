#ifndef PROTOCOL_H
#define PROTOCOL_H

#include "test.h"
#include <stdint.h>

#define CMD_PING 1
#define CMD_DRIVE_MOTOR 2
#define CMD_STOP_MOTOR 3
#define CMD_STOP_ALL_MOTORS 4
#define CMD_TURN_SERVO 5
#define CMD_APPLY_CONFIG 6

#define MSG_TO_SRV_PONG 0x01
#define MSG_TO_SRV_MY_INFO 0x02

#define PUPPY_PROTOCOL_VERSION 1

enum MotorType {
	DC_MOTOR = 0,
	SERVO_MOTOR = 1,
};

typedef struct {
	int motor_id;
	enum MotorType motor_type;
	int speed;
	int steps;
	int step_time;
	int angle;
} DriveMotorCommand;

typedef struct {
	int motor_id;
} StopMotorCommand;

typedef struct {
	int servo_id;
	int angle;
	int duration_ms;
} TurnServoCommand;

union Command {
	DriveMotorCommand drive_motor;
	StopMotorCommand stop_motor;
	TurnServoCommand turn_servo;
	struct {
		const uint8_t *data;
		uint16_t length;
	} apply_config;
};

typedef struct {
	int cmd_type;
	union Command cmd;
} CommandPacket;

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
	case CMD_TURN_SERVO:
		cmd_packet->cmd_type = CMD_TURN_SERVO;
		cmd_packet->cmd.turn_servo.servo_id =
		    (payload_len >= 1) ? payload[0] : 0;
		cmd_packet->cmd.turn_servo.angle =
		    (payload_len >= 3) ? (int16_t)(payload[1] | (payload[2] << 8)) : 0;
		cmd_packet->cmd.turn_servo.duration_ms =
		    (payload_len >= 5) ? (int16_t)(payload[3] | (payload[4] << 8)) : 0;
		break;
	case CMD_APPLY_CONFIG:
		cmd_packet->cmd_type = CMD_APPLY_CONFIG;
		cmd_packet->cmd.apply_config.data = payload;
		cmd_packet->cmd.apply_config.length = (uint16_t)payload_len;
		break;
	default:
		break;
	}
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

TEST(parse_turn_servo_test) {
	uint8_t data[] = {
	    0x01,                       // version
	    CMD_TURN_SERVO, 0x03, 0x00, // payload length = 3 (LE)

	    // Payload (3 bytes):
	    0x02,      // servo_id
	    0x2D, 0x00 // angle = 45
	};

	CommandPacket cmd_packet;
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_TURN_SERVO);
	ASSERT_EQ(cmd_packet.cmd.turn_servo.servo_id, 2);
	ASSERT_EQ(cmd_packet.cmd.turn_servo.angle, 45);
	ASSERT_EQ(cmd_packet.cmd.turn_servo.duration_ms, 0);
}

TEST(parse_turn_servo_with_timeout_test) {
	uint8_t data[] = {
	    0x01,                       // version
	    CMD_TURN_SERVO, 0x05, 0x00, // payload length = 5 (LE)

	    // Payload (5 bytes):
	    0x01,       // servo_id
	    0x2D, 0x00, // angle = 45
	    0xF4, 0x01, // duration_ms = 500
	};

	CommandPacket cmd_packet;
	parse_cmd(data, &cmd_packet);

	ASSERT_EQ(cmd_packet.cmd_type, CMD_TURN_SERVO);
	ASSERT_EQ(cmd_packet.cmd.turn_servo.servo_id, 1);
	ASSERT_EQ(cmd_packet.cmd.turn_servo.angle, 45);
	ASSERT_EQ(cmd_packet.cmd.turn_servo.duration_ms, 500);
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

#endif // PROTOCOL_H
