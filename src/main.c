
// Include unistd.h for usleep
#include <stdint.h>

#define LEFT_UP_MOTOR_EN 0
#define LEFT_UP_MOTOR_IN1 1
#define LEFT_UP_MOTOR_IN2 2

#define RIGHT_UP_MOTOR_EN 3
#define RIGHT_UP_MOTOR_IN1 4
#define RIGHT_UP_MOTOR_IN2 5

#define LEFT_DOWN_MOTOR_EN 6
#define LEFT_DOWN_MOTOR_IN1 7
#define LEFT_DOWN_MOTOR_IN2 8

#define RIGHT_DOWN_MOTOR_EN 9
#define RIGHT_DOWN_MOTOR_IN1 10
#define RIGHT_DOWN_MOTOR_IN2 11

#define RECV_CMD_MOVE_FORWARD 1
#define RECV_CMD_ROTATE_LEFT 2
#define RECV_CMD_ROTATE_RIGHT 3
#define RECV_CMD_MOVE_BACKWARD 4
#define RECV_CMD_STOP 5
#define RECV_CMD_ENABLE_WIFI 6
#define RECV_CMD_DISABLE_WIFI 7
#define RECV_CMD_ENABLE_BLE 8
#define RECV_CMD_DISABLE_BLE 9
#define RECV_REQ_INFO 10
#define RECV_SOFTWARE_UPDATE_START 11
#define RECV_SOFTWARE_UPDATE_FRAME 12

#define SEND_INFO 1

#define SOFTWARE_UPDATE_ADDR 0x10000

int turn_right(int speed) {
	const int pwm_duty = speed; // Use speed parameter for motor speed

	// Clockwise: left motors forward, right motors backward
	// Upper motors
	po_pwm_set_duty(0, pwm_duty);
	po_gpio_write(LEFT_UP_MOTOR_IN1, 1);
	po_gpio_write(LEFT_UP_MOTOR_IN2, 0);

	po_pwm_set_duty(1, pwm_duty);
	po_gpio_write(RIGHT_UP_MOTOR_IN1, 0);
	po_gpio_write(RIGHT_UP_MOTOR_IN2, 1);

	// Lower motors
	po_pwm_set_duty(2, pwm_duty);
	po_gpio_write(LEFT_DOWN_MOTOR_IN1, 1);
	po_gpio_write(LEFT_DOWN_MOTOR_IN2, 0);

	po_pwm_set_duty(3, pwm_duty);
	po_gpio_write(RIGHT_DOWN_MOTOR_IN1, 0);
	po_gpio_write(RIGHT_DOWN_MOTOR_IN2, 1);

	return 0;
}

int turn_left(int speed) {
	const int pwm_duty = speed; // Use speed parameter for motor speed

	// Anticlockwise: left motors backward, right motors forward
	// Upper motors
	po_pwm_set_duty(0, pwm_duty);
	po_gpio_write(LEFT_UP_MOTOR_IN1, 0);
	po_gpio_write(LEFT_UP_MOTOR_IN2, 1);

	po_pwm_set_duty(1, pwm_duty);
	po_gpio_write(RIGHT_UP_MOTOR_IN1, 1);
	po_gpio_write(RIGHT_UP_MOTOR_IN2, 0);

	// Lower motors
	po_pwm_set_duty(2, pwm_duty);
	po_gpio_write(LEFT_DOWN_MOTOR_IN1, 0);
	po_gpio_write(LEFT_DOWN_MOTOR_IN2, 1);

	po_pwm_set_duty(3, pwm_duty);
	po_gpio_write(RIGHT_DOWN_MOTOR_IN1, 1);
	po_gpio_write(RIGHT_DOWN_MOTOR_IN2, 0);

	return 0;
}

int forward(int speed) {
	const int pwm_duty = speed; // Use speed parameter for motor speed

	// Set left motors forward and right motors forward
	// Upper motors
	po_pwm_set_duty(0, pwm_duty);
	po_gpio_write(LEFT_UP_MOTOR_IN1, 1);
	po_gpio_write(LEFT_UP_MOTOR_IN2, 0);

	po_pwm_set_duty(1, pwm_duty);
	po_gpio_write(RIGHT_UP_MOTOR_IN1, 0);
	po_gpio_write(RIGHT_UP_MOTOR_IN2, 1);

	// Lower motors
	po_pwm_set_duty(2, pwm_duty);
	po_gpio_write(LEFT_DOWN_MOTOR_IN1, 1);
	po_gpio_write(LEFT_DOWN_MOTOR_IN2, 0);

	po_pwm_set_duty(3, pwm_duty);
	po_gpio_write(RIGHT_DOWN_MOTOR_IN1, 0);
	po_gpio_write(RIGHT_DOWN_MOTOR_IN2, 1);

	return 0;
}

int backward(int speed) {
	const int pwm_duty = speed; // Use speed parameter for motor speed

	// Set left motors backward and right motors backward
	// Upper motors
	po_pwm_set_duty(0, pwm_duty);
	po_gpio_write(LEFT_UP_MOTOR_IN1, 0);
	po_gpio_write(LEFT_UP_MOTOR_IN2, 1);

	po_pwm_set_duty(1, pwm_duty);
	po_gpio_write(RIGHT_UP_MOTOR_IN1, 1);
	po_gpio_write(RIGHT_UP_MOTOR_IN2, 0);

	// Lower motors
	po_pwm_set_duty(2, pwm_duty);
	po_gpio_write(LEFT_DOWN_MOTOR_IN1, 0);
	po_gpio_write(LEFT_DOWN_MOTOR_IN2, 1);

	po_pwm_set_duty(3, pwm_duty);
	po_gpio_write(RIGHT_DOWN_MOTOR_IN1, 1);
	po_gpio_write(RIGHT_DOWN_MOTOR_IN2, 0);

	return 0;
}

int stop() {
	// Stop all motors by setting PWM duty to 0 and clearing motor control pins
	po_pwm_set_duty(0, 0);
	po_pwm_set_duty(1, 0);
	po_pwm_set_duty(2, 0);
	po_pwm_set_duty(3, 0);

	po_gpio_write(LEFT_UP_MOTOR_IN1, 0);
	po_gpio_write(LEFT_UP_MOTOR_IN2, 0);
	po_gpio_write(RIGHT_UP_MOTOR_IN1, 0);
	po_gpio_write(RIGHT_UP_MOTOR_IN2, 0);

	po_gpio_write(LEFT_DOWN_MOTOR_IN1, 0);
	po_gpio_write(LEFT_DOWN_MOTOR_IN2, 0);
	po_gpio_write(RIGHT_DOWN_MOTOR_IN1, 0);
	po_gpio_write(RIGHT_DOWN_MOTOR_IN2, 0);

	return 0;
}

void handle_msg(uint8_t *data, int size) {
	// Assuming data is a string with the following format: "forward 1000"
	// where the first word is the command and the second word is the duration
	// in milliseconds
	char command[10];
	int duration;
	sscanf(data, "%s %d", command, &duration);

	if (strcmp(command, "forward") == 0) {
		forward();
		po_sleep(duration);
		stop();
	} else if (strcmp(command, "backward") == 0) {
		backward();
		po_sleep(duration);
		stop();
	} else if (strcmp(command, "left") == 0) {
		turn_left(duration);
		po_sleep(duration);
		stop();
	} else if (strcmp(command, "right") == 0) {
		turn_right();
		po_sleep(duration);
		stop();
	}
}

int software_update_offset = 0;
int software_update_size = 0;

void handle_cmd(int cmd, uint8_t *payload, int size) {
	switch (cmd) {
	case RECV_CMD_MOVE_FORWARD:
		uint16_t speed = (uint16_t)payload[0];
		forward(speed);
		break;
	case RECV_CMD_ROTATE_LEFT:
		uint16_t speed = (uint16_t)payload[0];
		turn_left(speed);
		break;
	case RECV_CMD_ROTATE_RIGHT:
		uint16_t speed = (uint16_t)payload[0];
		turn_right(speed);
		break;
	case RECV_CMD_MOVE_BACKWARD:
		uint16_t speed = (uint16_t)payload[0];
		backward(speed);
		break;
	case RECV_CMD_STOP:
		stop();
		break;
	case RECV_REQ_INFO:
		int temp = po_temp_read();
		int voltage = po_voltage_read();
		int cpu_freq = po_cpu_freq_read();
		int reset_reason = po_get_reset_reason();
		break;
	case RECV_SOFTWARE_UPDATE_START:
		int app_version = (int)payload[0];
		int update_size = (int)payload[1];
		software_update_size = update_size;
		break;
	case RECV_SOFTWARE_UPDATE_FRAME:
		memcpy(SOFTWARE_UPDATE_ADDR + software_update_offset, payload, size);
		software_update_offset += size;
		if (software_update_offset == software_update_size) {
			po_restart();
		}
		break;
	default:
		break;
	}
}

uint8_t buffer[2048];
int ptr = 0;
void handle_raw_msg(uint8_t *data, int size) {
	uint16_t version = (uint16_t)data[0];
	uint16_t len = (uint16_t)data[0];
	uint16_t cmd = (uint16_t)data[1];

	handle_cmd(cmd, data + 2, len - 2);
}

int main() {}