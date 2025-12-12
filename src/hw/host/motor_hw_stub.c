#include "log.h"
#include "motor_hw.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <unistd.h>

static const char *TAG = "MOTOR_HW";

#define MAX_CHANNELS 16

typedef struct {
	bool valid;
	uint16_t freq_hz;
} pwm_freq_state;

typedef struct {
	bool valid;
	int gpio;
} pwm_pin_state;

typedef struct {
	bool valid;
	uint16_t freq_hz;
	uint16_t pulse_us;
} pwm_pulse_state;

typedef struct {
	bool valid;
	float duty;
} pwm_duty_state;

typedef struct {
	bool valid;
	int in1;
	int in2;
	bool forward;
	bool brake;
} hbridge_state;

static pwm_freq_state g_freq_state[MAX_CHANNELS];
static pwm_pin_state g_pin_state[MAX_CHANNELS];
static pwm_pulse_state g_pulse_state[MAX_CHANNELS];
static pwm_duty_state g_duty_state[MAX_CHANNELS];
static hbridge_state g_hbridge_state;
static int g_serial_fd = -1;
static int g_serial_warned = 0;
static uint32_t g_serial_baud = 0;
static uint32_t g_serial_baud_env = 0;

static const int PULSE_LOG_THRESHOLD_US = 5;
static const float DUTY_LOG_THRESHOLD = 0.01f;

int motor_hw_init(void) {
	log_info(TAG, "Motor hardware stub initialized");
	return 0;
}

static speed_t choose_baud(uint32_t baud) {
	switch (baud) {
	case 9600:
		return B9600;
	case 19200:
		return B19200;
	case 38400:
		return B38400;
	case 57600:
		return B57600;
	case 115200:
		return B115200;
#ifdef B230400
	case 230400:
		return B230400;
#endif
#ifdef B460800
	case 460800:
		return B460800;
#endif
#ifdef B921600
	case 921600:
		return B921600;
#endif
	default:
		return B115200;
	}
}

static uint32_t env_serial_baud(void) {
	if (g_serial_baud_env)
		return g_serial_baud_env;
	const char *env = getenv("SERIAL_BAUD");
	if (!env || !*env)
		return 0;
	char *end = NULL;
	long val = strtol(env, &end, 10);
	if (end == env || val <= 0)
		return 0;
	g_serial_baud_env = (uint32_t)val;
	return g_serial_baud_env;
}

static int ensure_serial_open(uint32_t baud_rate) {
	uint32_t desired_baud = env_serial_baud();
	if (desired_baud == 0)
		desired_baud = baud_rate;
	if (desired_baud == 0)
		desired_baud = 1000000;

	if (g_serial_fd >= 0 && g_serial_baud == desired_baud)
		return g_serial_fd;

	const char *port = getenv("SERIAL_PORT");
	if (!port || !*port) {
		if (!g_serial_warned) {
			log_warn(TAG, "SERIAL_PORT env not set; smart servo packets will "
			              "be logged only");
			g_serial_warned = 1;
		}
		return -1;
	}

	int fd = open(port, O_RDWR | O_NOCTTY | O_NONBLOCK);
	if (fd < 0) {
		log_error(TAG, "Failed to open serial port %s: %s", port,
		          strerror(errno));
		return -1;
	}

	struct termios tio;
	if (tcgetattr(fd, &tio) != 0) {
		log_error(TAG, "tcgetattr failed for %s: %s", port, strerror(errno));
		close(fd);
		return -1;
	}

	cfmakeraw(&tio);
	speed_t speed = choose_baud(desired_baud);
	if (cfsetspeed(&tio, speed) != 0) {
		log_error(TAG, "cfsetspeed failed for %s: %s", port, strerror(errno));
		close(fd);
		return -1;
	}

	tio.c_cflag |= (CLOCAL | CREAD);
	if (tcsetattr(fd, TCSANOW, &tio) != 0) {
		log_error(TAG, "tcsetattr failed for %s: %s", port, strerror(errno));
		close(fd);
		return -1;
	}

	g_serial_fd = fd;
	g_serial_baud = desired_baud;
	log_info(TAG, "Opened serial port %s at %" PRIu32 " baud", port,
	         desired_baud);
	return fd;
}

void motor_hw_ensure_pwm(uint8_t channel, uint16_t freq_hz) {
	if (channel >= MAX_CHANNELS) {
		return;
	}

	pwm_freq_state *state = &g_freq_state[channel];
	if (state->valid && state->freq_hz == freq_hz) {
		return;
	}

	state->valid = true;
	state->freq_hz = freq_hz;
	log_info(TAG, "Ensure PWM channel %u at %u Hz", channel, freq_hz);
}

void motor_hw_bind_pwm_pin(uint8_t channel, int gpio) {
	if (channel >= MAX_CHANNELS) {
		return;
	}

	pwm_pin_state *state = &g_pin_state[channel];
	if (state->valid && state->gpio == gpio) {
		return;
	}

	state->valid = true;
	state->gpio = gpio;
	log_info(TAG, "Bind PWM channel %u to pin %d", channel, gpio);
}

void motor_hw_set_pwm_pulse_us(uint8_t channel, uint16_t freq_hz,
                               uint16_t pulse_us) {
	if (channel >= MAX_CHANNELS) {
		return;
	}

	pwm_pulse_state *state = &g_pulse_state[channel];
	if (state->valid && state->freq_hz == freq_hz) {
		int delta = abs((int)state->pulse_us - (int)pulse_us);
		if (delta < PULSE_LOG_THRESHOLD_US) {
			state->pulse_us = pulse_us;
			return;
		}
	}

	state->valid = true;
	state->freq_hz = freq_hz;
	state->pulse_us = pulse_us;

	float duty =
	    freq_hz == 0 ? 0.0f : ((float)pulse_us * (float)freq_hz) / 10000.0f;
	log_info(TAG,
	         "Set PWM pulse: channel=%u freq=%uHz pulse=%uus (duty=%.2f%%)",
	         channel, freq_hz, pulse_us, duty);
}

static float clamp_float_01(float value) {
	if (value < 0.0f) {
		return 0.0f;
	}
	if (value > 1.0f) {
		return 1.0f;
	}
	return value;
}

void motor_hw_set_pwm_duty(uint8_t channel, float duty_0_to_1) {
	if (channel >= MAX_CHANNELS) {
		return;
	}

	float duty = clamp_float_01(duty_0_to_1);
	pwm_duty_state *state = &g_duty_state[channel];
	if (state->valid && fabsf(state->duty - duty) < DUTY_LOG_THRESHOLD) {
		state->duty = duty;
		return;
	}

	state->valid = true;
	state->duty = duty;
	log_info(TAG, "Set PWM duty: channel=%u duty=%.2f%%", channel,
	         duty * 100.0f);
}

void motor_hw_configure_hbridge(int in1, int in2, bool forward, bool brake) {
	hbridge_state *state = &g_hbridge_state;
	if (state->valid && state->in1 == in1 && state->in2 == in2 &&
	    state->forward == forward && state->brake == brake) {
		return;
	}

	state->valid = true;
	state->in1 = in1;
	state->in2 = in2;
	state->forward = forward;
	state->brake = brake;

	log_info(TAG, "Configure H-bridge: in1=%d in2=%d direction=%s mode=%s", in1,
	         in2, forward ? "forward" : "reverse", brake ? "brake" : "coast");
}

int motor_hw_configure_smartbus(uint8_t uart_port, int tx_pin, int rx_pin,
                                uint32_t baud_rate) {
	(void)uart_port;
	(void)tx_pin;
	(void)rx_pin;
	if (baud_rate == 0)
		baud_rate = 1000000;
	int fd = ensure_serial_open(baud_rate);
	if (fd < 0)
		return -1;
	return 0;
}

void motor_hw_smartbus_move(uint8_t uart_port, uint8_t servo_id,
                            uint16_t angle_x10, uint16_t duration_ms) {
	(void)uart_port;
	uint8_t packet[10];
	uint16_t time_clamped = duration_ms > 30000 ? 30000 : duration_ms;
	uint16_t pos_x1000 = (uint16_t)((angle_x10 * 100u) / 1800u);
	if (pos_x1000 > 1000)
		pos_x1000 = 1000;

	packet[0] = 0x55;
	packet[1] = 0x55;
	packet[2] = servo_id;
	packet[3] = 7;
	packet[4] = 1;
	packet[5] = (uint8_t)(pos_x1000 & 0xFFu);
	packet[6] = (uint8_t)((pos_x1000 >> 8) & 0xFFu);
	packet[7] = (uint8_t)(time_clamped & 0xFFu);
	packet[8] = (uint8_t)((time_clamped >> 8) & 0xFFu);
	uint32_t sum = 0;
	for (size_t i = 2; i < sizeof(packet) - 1; ++i)
		sum += packet[i];
	packet[9] = (uint8_t)(~(sum & 0xFFu));

	int fd = ensure_serial_open(g_serial_baud ? g_serial_baud : 1000000);
	if (fd >= 0) {
		ssize_t written = write(fd, packet, sizeof(packet));
		if (written != (ssize_t)sizeof(packet)) {
			log_warn(TAG, "Short write to serial port (%zd/10)", written);
		}
	}

	log_info(
	    TAG,
	    "Smart servo move: id=%u angle_x10=%u duration_ms=%u via serial fd=%d",
	    (unsigned)servo_id, (unsigned)angle_x10, (unsigned)time_clamped, fd);
}
