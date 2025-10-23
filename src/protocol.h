#include "test.h"
#include <stdint.h>

#define CMD_PING 1
#define CMD_DRIVE_MOTOR 2
#define CMD_STOP_MOTOR 3
#define CMD_STOP_ALL_MOTORS 4
#define CMD_TURN_SERVO 5

#define MSG_TO_SRV_PONG 0x01

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
} TurnServoCommand;

union Command {
	DriveMotorCommand drive_motor;
	StopMotorCommand stop_motor;
	TurnServoCommand turn_servo;
};

typedef struct {
	int cmd_type;
	union Command cmd;
} CommandPacket;

static inline void parse_cmd(uint8_t *data, CommandPacket *cmd_packet) {
	int version = data[0];
	int cmd_type = data[1];
	int payload_len = data[2] | (data[3] << 8);
	uint8_t *payload = &data[4];

	switch (cmd_type) {
	case CMD_PING:
		cmd_packet->cmd_type = CMD_PING;
		break;
	case CMD_DRIVE_MOTOR:
		cmd_packet->cmd_type = CMD_DRIVE_MOTOR;
		cmd_packet->cmd.drive_motor.motor_id = payload[0];
		// cmd_packet->cmd.drive_motor.motor_type = (enum MotorType)payload[1];
		cmd_packet->cmd.drive_motor.speed = (int8_t)payload[1];
		// if (cmd_packet->cmd.drive_motor.motor_type == SERVO_MOTOR &&
		//     payload_len >= 5) {
		// 	cmd_packet->cmd.drive_motor.angle =
		// 	    (int16_t)(payload[3] | (payload[4] << 8));
		// } else if (payload_len >= 7) {
		// 	cmd_packet->cmd.drive_motor.steps =
		// 	    (int16_t)(payload[3] | (payload[4] << 8));
		// 	cmd_packet->cmd.drive_motor.step_time =
		// 	    (int16_t)(payload[5] | (payload[6] << 8));
		// }
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
		if (payload_len >= 3) {
			cmd_packet->cmd.turn_servo.servo_id = payload[0];
			cmd_packet->cmd.turn_servo.angle =
			    (int16_t)(payload[1] | (payload[2] << 8));
		}
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
}
