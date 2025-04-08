#ifndef CMD_H
#define CMD_H

// Motor A GPIOs
#define IN1_GPIO    GPIO_NUM_5
#define IN2_GPIO    GPIO_NUM_18
#define ENA_GPIO    GPIO_NUM_19

// Motor B GPIOs
#define IN3_GPIO    GPIO_NUM_17
#define IN4_GPIO    GPIO_NUM_16
#define ENB_GPIO    GPIO_NUM_4

// Motor C GPIOs
#define IN5_GPIO    GPIO_NUM_21
#define IN6_GPIO    GPIO_NUM_22
#define ENC_GPIO    GPIO_NUM_23

// Motor D GPIOs
#define IN7_GPIO    GPIO_NUM_25
#define IN8_GPIO    GPIO_NUM_26
#define END_GPIO    GPIO_NUM_27

#include "protocol.h"
#include "hardware.h"

void handle_cmd(CommandPacket *cmd) {
	switch (cmd->cmd_type) {
	case CMD_DRIVE_MOTOR:
		// Handle drive motor command
		break;
	case CMD_STOP_MOTOR:
		// Handle stop motor command
		break;
	case STOP_ALL_MOTORS:
		// Handle stop all motors command
		break;
	default:
		break;
	}
}

#endif