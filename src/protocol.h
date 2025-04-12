#include <stdint.h>
#include "test.h"

#define CMD_PING 1
#define CMD_DRIVE_MOTOR 2
#define CMD_STOP_MOTOR 3
#define CMD_STOP_ALL_MOTORS 4

#define MSG_TO_SRV_TYPE 0x01

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

union Command {
	DriveMotorCommand drive_motor;
	StopMotorCommand stop_motor;
};

typedef struct {
	int cmd_type;
	union Command cmd;
} CommandPacket;

void parse_cmd(uint8_t *data, CommandPacket *cmd_packet) {
	int version = data[0];
	int cmd_type = data[1];
	int payload_len = data[2];
	uint8_t *payload = &data[4];

	switch (cmd_type)
	{
	case CMD_PING:
		cmd_packet->cmd_type = CMD_PING;
		break;
	case CMD_DRIVE_MOTOR:
		cmd_packet->cmd_type = CMD_DRIVE_MOTOR;
		int motor_id = payload[0];
		enum MotorType motor_type = (enum MotorType)payload[1];
		cmd_packet->cmd.drive_motor.speed = payload[2];
		cmd_packet->cmd.drive_motor.steps = payload[3];
		cmd_packet->cmd.drive_motor.step_time = payload[5];
		cmd_packet->cmd.drive_motor.angle = payload[7];
		break;
	case CMD_STOP_MOTOR:
		cmd_packet->cmd_type = CMD_STOP_MOTOR;
		cmd_packet->cmd.stop_motor.motor_id = payload[0];
		break;
	case CMD_STOP_ALL_MOTORS:
		cmd_packet->cmd_type = CMD_STOP_ALL_MOTORS;
		break;
	default:
		break;
	}
}

// typedef struct {

// } 

// void serialize_msg_to_server() {

// }

TEST(parse_cmd_test) {
	uint8_t data[] = { 0x01, CMD_DRIVE_MOTOR, 0x08, 0x00, 0x01, 0x00, 0x02, 0x03, 0x04, 0x05, 0x06 };
	CommandPacket cmd_packet;
	parse_cmd(data, &cmd_packet);
	ASSERT_EQ(cmd_packet.cmd_type, CMD_DRIVE_MOTOR);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.motor_id, 1);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.speed, 2);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.steps, 3);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.step_time, 5);
	ASSERT_EQ(cmd_packet.cmd.drive_motor.angle, 7);
}