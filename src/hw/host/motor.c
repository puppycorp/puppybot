#include "log.h"
#include "motor_hw.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <math.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

#ifdef __APPLE__
#include <IOKit/serial/ioss.h>
#endif

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
static int g_serial_baud_warned = 0;
static uint32_t g_serial_baud = 0;
static uint32_t g_serial_baud_env = 0;
static pthread_mutex_t g_serial_mu = PTHREAD_MUTEX_INITIALIZER;

static const int PULSE_LOG_THRESHOLD_US = 5;
static const float DUTY_LOG_THRESHOLD = 0.01f;

int motor_hw_init(void) {
	log_info(TAG, "Motor hardware stub initialized");
	return 0;
}

static uint8_t smartbus_checksum(const uint8_t *packet, size_t len);

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
#ifdef B500000
	case 500000:
		return B500000;
#endif
#ifdef B921600
	case 921600:
		return B921600;
#endif
#ifdef B1000000
	case 1000000:
		return B1000000;
#endif
	default:
		return (speed_t)0;
	}
}

static uint32_t env_serial_baud(void) {
	if (g_serial_baud_env)
		return g_serial_baud_env;
	const char *env = getenv("BAUD");
	if (!env || !*env)
		return 0;
	char *end = NULL;
	long val = strtol(env, &end, 10);
	if (end == env || val <= 0)
		return 0;
	g_serial_baud_env = (uint32_t)val;
	return g_serial_baud_env;
}

static int set_platform_baud(int fd, uint32_t baud) {
#ifdef __APPLE__
	if (baud == 0)
		return -1;
	if (choose_baud(baud) != 0)
		return 0;
	if (ioctl(fd, IOSSIOSPEED, &baud) != 0) {
		log_warn(TAG, "IOSSIOSPEED failed for baud %" PRIu32 ": %s", baud,
		         strerror(errno));
		return -1;
	}
	return 0;
#else
	(void)fd;
	(void)baud;
	return 0;
#endif
}

static void clear_modem_lines(int fd) {
	int bits = 0;
	bits |= TIOCM_DTR;
	bits |= TIOCM_RTS;
	if (ioctl(fd, TIOCMBIC, &bits) != 0) {
		log_warn(TAG, "Failed to clear DTR/RTS: %s", strerror(errno));
	}
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
	if (speed == 0) {
		speed = B115200;
		if (!g_serial_baud_warned) {
			log_warn(
			    TAG,
			    "Baud %" PRIu32
			    " not available in termios; attempting platform-specific setup",
			    desired_baud);
			g_serial_baud_warned = 1;
		}
	}
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

	(void)set_platform_baud(fd, desired_baud);
	clear_modem_lines(fd);

	g_serial_fd = fd;
	g_serial_baud = desired_baud;
	log_info(TAG, "Opened serial port %s at %" PRIu32 " baud", port,
	         desired_baud);
	return fd;
}

static uint32_t monotonic_ms(void) {
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint32_t)((uint64_t)ts.tv_sec * 1000ULL + ts.tv_nsec / 1000000ULL);
}

static int read_exact_timeout(int fd, uint8_t *out, size_t len,
                              int timeout_ms) {
	if (!out && len)
		return -1;
	uint32_t deadline =
	    monotonic_ms() + (timeout_ms < 0 ? 0 : (uint32_t)timeout_ms);
	size_t got = 0;
	while (got < len) {
		uint32_t now = monotonic_ms();
		if (timeout_ms >= 0 && now >= deadline)
			return -2;
		int remaining = timeout_ms < 0 ? 100 : (int)(deadline - now);
		if (remaining < 1)
			remaining = 1;

		fd_set rfds;
		FD_ZERO(&rfds);
		FD_SET(fd, &rfds);
		struct timeval tv;
		tv.tv_sec = remaining / 1000;
		tv.tv_usec = (remaining % 1000) * 1000;
		int sel = select(fd + 1, &rfds, NULL, NULL, &tv);
		if (sel < 0) {
			if (errno == EINTR)
				continue;
			return -3;
		}
		if (sel == 0)
			continue;

		ssize_t n = read(fd, out + got, len - got);
		if (n < 0) {
			if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)
				continue;
			return -4;
		}
		if (n == 0)
			continue;
		got += (size_t)n;
	}
	return 0;
}

typedef struct {
	uint8_t id;
	uint8_t cmd_or_err;
	uint8_t params[64];
	uint8_t params_len;
} smartbus_frame_t;

static int smartbus_read_frame(int fd, smartbus_frame_t *f, int timeout_ms) {
	if (!f)
		return -1;

	uint8_t b = 0;
	uint8_t prev = 0;
	uint32_t deadline =
	    monotonic_ms() + (timeout_ms < 0 ? 0 : (uint32_t)timeout_ms);
	while (1) {
		uint32_t now = monotonic_ms();
		if (timeout_ms >= 0 && now >= deadline)
			return -2;
		int remaining = timeout_ms < 0 ? 100 : (int)(deadline - now);
		if (remaining < 1)
			remaining = 1;
		if (read_exact_timeout(fd, &b, 1, remaining) != 0)
			continue;
		if (prev == 0xFF && b == 0xFF)
			break;
		prev = b;
	}

	uint8_t hdr[2];
	if (read_exact_timeout(fd, hdr, sizeof(hdr), timeout_ms) != 0)
		return -3;
	uint8_t id = hdr[0];
	uint8_t len = hdr[1];
	size_t frame_len = (size_t)len + 4;
	if (frame_len < 6 || frame_len > 128)
		return -4;

	uint8_t packet[128];
	packet[0] = 0xFF;
	packet[1] = 0xFF;
	packet[2] = id;
	packet[3] = len;
	if (read_exact_timeout(fd, packet + 4, frame_len - 4, timeout_ms) != 0)
		return -5;

	uint8_t expected = smartbus_checksum(packet, frame_len - 1);
	uint8_t got = packet[frame_len - 1];
	if (expected != got)
		return -6;

	f->id = id;
	f->cmd_or_err = packet[4];
	uint8_t params_len = (uint8_t)(len - 2);
	if (params_len > sizeof(f->params))
		params_len = (uint8_t)sizeof(f->params);
	f->params_len = params_len;
	if (params_len) {
		memcpy(f->params, &packet[5], params_len);
	}
	return 0;
}

static int smartbus_txrx(int fd, const uint8_t *tx, int txlen,
                         smartbus_frame_t *rx, int timeout_ms) {
	if (!tx || txlen <= 0 || !rx)
		return -1;

	tcflush(fd, TCIFLUSH);
	ssize_t written = write(fd, tx, (size_t)txlen);
	if (written != txlen)
		return -2;
	tcdrain(fd);
	usleep(1000);
	return smartbus_read_frame(fd, rx, timeout_ms);
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

static uint8_t smartbus_checksum(const uint8_t *packet, size_t len) {
	uint32_t sum = 0;
	for (size_t i = 2; i < len; ++i)
		sum += packet[i];
	return (uint8_t)(~(sum & 0xFFu));
}

static int smartbus_build(uint8_t *out, size_t out_cap, uint8_t id,
                          uint8_t inst, const uint8_t *params,
                          uint8_t params_len) {
	uint8_t len = (uint8_t)(params_len + 2);
	size_t frame_len = (size_t)len + 4;
	if (out_cap < frame_len)
		return -1;

	out[0] = 0xFF;
	out[1] = 0xFF;
	out[2] = id;
	out[3] = len;
	out[4] = inst;
	for (uint8_t i = 0; i < params_len; ++i)
		out[5 + i] = params[i];
	out[frame_len - 1] = smartbus_checksum(out, frame_len - 1);
	return (int)frame_len;
}

static uint16_t angle_to_position(uint16_t angle_x10) {
	float degrees = angle_x10 / 10.0f;
	float scaled = (degrees / 240.0f) * 1000.0f;
	if (scaled < 0.0f)
		scaled = 0.0f;
	if (scaled > 1000.0f)
		scaled = 1000.0f;
	return (uint16_t)lroundf(scaled);
}

void motor_hw_smartbus_move(uint8_t uart_port, uint8_t servo_id,
                            uint16_t angle_x10, uint16_t duration_ms) {
	(void)uart_port;
	uint16_t time_clamped = duration_ms > 30000 ? 30000 : duration_ms;
	uint16_t pos = angle_to_position(angle_x10);

	uint8_t params[7];
	params[0] = (uint8_t)SMARTBUS_ADDR_GOAL_POSITION_L;
	params[1] = (uint8_t)(pos & 0xFFu);
	params[2] = (uint8_t)((pos >> 8) & 0xFFu);
	params[3] = (uint8_t)(time_clamped & 0xFFu);
	params[4] = (uint8_t)((time_clamped >> 8) & 0xFFu);
	params[5] = 0;
	params[6] = 0;

	uint8_t packet[16];
	int plen =
	    smartbus_build(packet, sizeof(packet), servo_id,
	                   (uint8_t)SMARTBUS_INST_WRITE, params, sizeof(params));
	if (plen <= 0) {
		log_warn(TAG, "Failed to build smart servo packet");
		return;
	}

	pthread_mutex_lock(&g_serial_mu);
	int fd = ensure_serial_open(g_serial_baud ? g_serial_baud : 1000000);
	if (fd >= 0) {
		ssize_t written = write(fd, packet, (size_t)plen);
		if (written != plen) {
			log_warn(TAG, "Short write to serial port (%zd/%d)", written, plen);
		}
	}
	pthread_mutex_unlock(&g_serial_mu);

	log_info(
	    TAG,
	    "Smart servo move: id=%u angle_x10=%u duration_ms=%u via serial fd=%d",
	    (unsigned)servo_id, (unsigned)angle_x10, (unsigned)time_clamped, fd);
}

static void smartbus_write_bytes(uint8_t servo_id, uint8_t addr,
                                 const uint8_t *data, uint8_t data_len) {
	if (!data && data_len)
		return;
	uint8_t params[1 + 16];
	if (data_len > 16)
		return;
	params[0] = addr;
	for (uint8_t i = 0; i < data_len; ++i)
		params[1 + i] = data[i];

	uint8_t packet[32];
	int plen = smartbus_build(packet, sizeof(packet), servo_id,
	                          (uint8_t)SMARTBUS_INST_WRITE, params,
	                          (uint8_t)(1 + data_len));
	if (plen <= 0) {
		log_warn(TAG, "Failed to build smart servo write packet");
		return;
	}

	pthread_mutex_lock(&g_serial_mu);
	int fd = ensure_serial_open(g_serial_baud ? g_serial_baud : 1000000);
	if (fd >= 0) {
		ssize_t written = write(fd, packet, (size_t)plen);
		if (written != plen) {
			log_warn(TAG, "Short write to serial port (%zd/%d)", written, plen);
		}
	}
	pthread_mutex_unlock(&g_serial_mu);
}

void motor_hw_smartbus_set_mode(uint8_t uart_port, uint8_t servo_id,
                                uint8_t mode) {
	(void)uart_port;
	smartbus_write_bytes(servo_id, (uint8_t)SMARTBUS_ADDR_MODE, &mode, 1);
	log_info(TAG, "Smart servo mode: id=%u mode=%u", (unsigned)servo_id,
	         (unsigned)mode);
}

void motor_hw_smartbus_set_wheel_speed(uint8_t uart_port, uint8_t servo_id,
                                       int16_t speed_raw, uint8_t acc) {
	(void)uart_port;
	uint8_t data[7];
	data[0] = acc;
	data[1] = 0;
	data[2] = 0;
	data[3] = 0;
	data[4] = 0;
	data[5] = (uint8_t)(speed_raw & 0xFF);
	data[6] = (uint8_t)((speed_raw >> 8) & 0xFF);
	smartbus_write_bytes(servo_id, (uint8_t)SMARTBUS_ADDR_ACC, data,
	                     sizeof(data));
	log_info(TAG, "Smart servo wheel: id=%u speed_raw=%d acc=%u",
	         (unsigned)servo_id, (int)speed_raw, (unsigned)acc);
}

void motor_hw_smartbus_write_u8(uint8_t uart_port, uint8_t servo_id,
                                uint8_t addr, uint8_t value) {
	(void)uart_port;
	smartbus_write_bytes(servo_id, addr, &value, 1);
	log_info(TAG, "Smart servo write8: id=%u addr=%u value=%u",
	         (unsigned)servo_id, (unsigned)addr, (unsigned)value);
}

int motor_hw_smartbus_read_position(uint8_t uart_port, uint8_t servo_id,
                                    uint16_t *pos_raw_out) {
	(void)uart_port;
	if (!pos_raw_out)
		return -1;

	// Read 2 bytes from PRESENT_POSITION_L.
	uint8_t params[2];
	params[0] = (uint8_t)SMARTBUS_ADDR_PRESENT_POSITION_L;
	params[1] = 2;
	uint8_t tx[16];
	int txlen =
	    smartbus_build(tx, sizeof(tx), servo_id, (uint8_t)SMARTBUS_INST_READ,
	                   params, sizeof(params));
	if (txlen < 0)
		return -2;

	pthread_mutex_lock(&g_serial_mu);
	int fd = ensure_serial_open(g_serial_baud ? g_serial_baud : 1000000);
	if (fd < 0) {
		pthread_mutex_unlock(&g_serial_mu);
		return -3;
	}
	smartbus_frame_t rx;
	int r = smartbus_txrx(fd, tx, txlen, &rx, 50);
	pthread_mutex_unlock(&g_serial_mu);
	if (r != 0)
		return r;
	if (rx.id != servo_id)
		return -4;
	if (rx.params_len < 2)
		return -5;

	*pos_raw_out = (uint16_t)(rx.params[0] | (rx.params[1] << 8));
	return 0;
}

int motor_hw_smartbus_ping(uint8_t uart_port, uint8_t servo_id,
                           int timeout_ms) {
	(void)uart_port;
	if (timeout_ms <= 0)
		timeout_ms = 50;

	uint8_t tx[16];
	int txlen = smartbus_build(tx, sizeof(tx), servo_id,
	                           (uint8_t)SMARTBUS_CMD_PING, NULL, 0);
	if (txlen < 0)
		return -1;

	pthread_mutex_lock(&g_serial_mu);
	int fd = ensure_serial_open(g_serial_baud ? g_serial_baud : 1000000);
	if (fd < 0) {
		pthread_mutex_unlock(&g_serial_mu);
		return -2;
	}
	smartbus_frame_t rx;
	int r = smartbus_txrx(fd, tx, txlen, &rx, timeout_ms);
	pthread_mutex_unlock(&g_serial_mu);
	if (r != 0)
		return r;
	if (rx.id != servo_id)
		return -3;
	return 0;
}
