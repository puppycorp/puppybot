#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "motor_config.h"
#include "motor_hw.h"
#include <inttypes.h>
#include <math.h>
#include <string.h>

static const char *TAG = "motor_hw";

int motor_hw_init(void) { return 0; }

static inline uint32_t clamp_u32(uint32_t value, uint32_t max) {
	return value > max ? max : value;
}

static inline uint32_t pwm_duty_from_us(uint16_t freq_hz, uint16_t pulse_us) {
	if (freq_hz == 0)
		return 0;
	uint32_t period_us = 1000000UL / (uint32_t)freq_hz;
	if (period_us == 0)
		return 0;
	uint64_t duty = (uint64_t)pulse_us * ((1u << 16) - 1);
	duty /= period_us;
	return clamp_u32((uint32_t)duty, (1u << 16) - 1);
}

static inline uint32_t pwm_duty_from_ratio(float duty) {
	if (duty < 0.0f)
		duty = 0.0f;
	if (duty > 1.0f)
		duty = 1.0f;
	return (uint32_t)lroundf(duty * ((1u << 16) - 1));
}

static ledc_timer_t timer_for_channel(uint8_t ch) {
	return (ledc_timer_t)(LEDC_TIMER_0 + (ch / 4));
}

typedef struct {
	bool configured;
	int tx_pin;
	int rx_pin;
	uint32_t baud;
} smart_bus_state_t;

static smart_bus_state_t g_smart_buses[UART_NUM_MAX] = {0};
static SemaphoreHandle_t g_smartbus_mu[UART_NUM_MAX] = {0};

void motor_hw_ensure_pwm(uint8_t channel, uint16_t freq_hz) {
	ESP_LOGI(TAG, "Ensuring PWM channel %d at %d Hz", channel, freq_hz);
	ledc_timer_config_t tcfg = {
	    .speed_mode = LEDC_LOW_SPEED_MODE,
	    .duty_resolution = LEDC_TIMER_16_BIT,
	    .timer_num = timer_for_channel(channel),
	    .freq_hz = freq_hz,
	    .clk_cfg = LEDC_AUTO_CLK,
	};
	ledc_timer_config(&tcfg);
}

void motor_hw_bind_pwm_pin(uint8_t channel, int gpio) {
	ESP_LOGI(TAG, "Binding PWM channel %d to GPIO %d", channel, gpio);
	ledc_channel_config_t ccfg = {
	    .gpio_num = gpio,
	    .speed_mode = LEDC_LOW_SPEED_MODE,
	    .channel = (ledc_channel_t)channel,
	    .timer_sel = timer_for_channel(channel),
	    .duty = 0,
	    .hpoint = 0,
	};
	ledc_channel_config(&ccfg);
}

void motor_hw_set_pwm_pulse_us(uint8_t channel, uint16_t freq_hz,
                               uint16_t pulse_us) {
	uint32_t duty = pwm_duty_from_us(freq_hz, pulse_us);
	ledc_set_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)channel, duty);
	ledc_update_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)channel);
}

void motor_hw_set_pwm_duty(uint8_t channel, float duty_ratio) {
	uint32_t duty = pwm_duty_from_ratio(duty_ratio);
	ledc_set_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)channel, duty);
	ledc_update_duty(LEDC_LOW_SPEED_MODE, (ledc_channel_t)channel);
}

void motor_hw_configure_hbridge(int in1, int in2, bool forward, bool brake) {
	if (in1 < 0 || in2 < 0)
		return;
	gpio_config_t cfg = {
	    .pin_bit_mask = (1ULL << in1) | (1ULL << in2),
	    .mode = GPIO_MODE_OUTPUT,
	    .pull_up_en = GPIO_PULLUP_DISABLE,
	    .pull_down_en = GPIO_PULLDOWN_DISABLE,
	    .intr_type = GPIO_INTR_DISABLE,
	};
	gpio_config(&cfg);
	if (brake) {
		int level = forward ? 1 : 0;
		gpio_set_level((gpio_num_t)in1, level);
		gpio_set_level((gpio_num_t)in2, level);
	} else {
		gpio_set_level((gpio_num_t)in1, forward ? 1 : 0);
		gpio_set_level((gpio_num_t)in2, forward ? 0 : 1);
	}
}

int motor_hw_configure_smartbus(uint8_t uart_port, int tx_pin, int rx_pin,
                                uint32_t baud_rate) {
	if (uart_port >= UART_NUM_MAX)
		return -1;
	if (baud_rate == 0)
		baud_rate = 1000000;

	smart_bus_state_t *bus = &g_smart_buses[uart_port];
	if (bus->configured && bus->tx_pin == tx_pin && bus->rx_pin == rx_pin &&
	    bus->baud == baud_rate) {
		return 0;
	}

	uart_config_t cfg = {.baud_rate = (int)baud_rate,
	                     .data_bits = UART_DATA_8_BITS,
	                     .parity = UART_PARITY_DISABLE,
	                     .stop_bits = UART_STOP_BITS_1,
	                     .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
	                     .source_clk = UART_SCLK_DEFAULT};

	uart_driver_install((uart_port_t)uart_port, 256, 0, 0, NULL, 0);
	uart_param_config((uart_port_t)uart_port, &cfg);
	uart_set_pin((uart_port_t)uart_port, tx_pin, rx_pin, UART_PIN_NO_CHANGE,
	             UART_PIN_NO_CHANGE);
	uart_set_mode((uart_port_t)uart_port, UART_MODE_UART);

	bus->configured = true;
	bus->tx_pin = tx_pin;
	bus->rx_pin = rx_pin;
	bus->baud = baud_rate;

	ESP_LOGI(TAG,
	         "Configured smart servo bus uart=%u tx=%d rx=%d baud=%" PRIu32,
	         (unsigned)uart_port, tx_pin, rx_pin, baud_rate);
	return 0;
}

static uint8_t smart_checksum(const uint8_t *packet, size_t len) {
	uint32_t sum = 0;
	for (size_t i = 2; i < len; ++i)
		sum += packet[i];
	return (uint8_t)(~(sum & 0xFFu));
}

// Build a SCServo/STS protocol 1.0 frame:
// 0xFF 0xFF ID LEN INST PARAMS... CHKSUM
// LEN = params_len + 2 (INST + CHKSUM).
static int smartbus_build(uint8_t *out, size_t out_cap, uint8_t id,
                          uint8_t inst, const uint8_t *params,
                          uint8_t params_len) {
	uint8_t len = (uint8_t)(params_len + 2);
	size_t frame_len = (size_t)len + 4; // total = LEN + HEADER0 HEADER1 ID LEN
	if (out_cap < frame_len)
		return -1;

	out[0] = 0xFF;
	out[1] = 0xFF;
	out[2] = id;
	out[3] = len;
	out[4] = inst;
	for (uint8_t i = 0; i < params_len; ++i)
		out[5 + i] = params[i];

	out[frame_len - 1] = smart_checksum(out, frame_len - 1);
	return (int)frame_len;
}

typedef struct {
	uint8_t id;
	uint8_t len;
	uint8_t cmd;
	uint8_t params[64];
	uint8_t params_len;
} smartbus_frame_t;

static int smartbus_read_frame(uart_port_t uart, smartbus_frame_t *f,
                               int timeout_ms) {
	if (!f)
		return -1;
	int64_t deadline = esp_timer_get_time() + (int64_t)timeout_ms * 1000LL;

	enum { S0, S1, SID, SLEN, SCMD, SPARAMS, SCKS } st = S0;
	uint8_t sum = 0;
	uint8_t params_needed = 0;
	uint8_t param_i = 0;
	uint8_t b = 0;

	while (esp_timer_get_time() < deadline) {
		int64_t now = esp_timer_get_time();
		int to_ms = (int)((deadline - now) / 1000LL);
		if (to_ms < 1)
			to_ms = 1;

		int n = uart_read_bytes(uart, &b, 1, pdMS_TO_TICKS(to_ms));
		if (n <= 0)
			continue;

		switch (st) {
		case S0:
			st = (b == 0xFF) ? S1 : S0;
			break;
		case S1:
			st = (b == 0xFF) ? SID : S0;
			break;
		case SID:
			f->id = b;
			sum = b;
			st = SLEN;
			break;
		case SLEN:
			f->len = b;
			sum = (uint8_t)(sum + b);
			// Status packet LEN includes ERROR + PARAMS + CHKSUM.
			// PARAMS bytes = LEN - 2.
			params_needed = (uint8_t)(b - 2);
			if (params_needed > sizeof(f->params))
				return -2;
			f->params_len = params_needed;
			st = SCMD;
			break;
		case SCMD:
			f->cmd = b;
			sum = (uint8_t)(sum + b);
			param_i = 0;
			st = (params_needed == 0) ? SCKS : SPARAMS;
			break;
		case SPARAMS:
			f->params[param_i++] = b;
			sum = (uint8_t)(sum + b);
			if (param_i >= params_needed)
				st = SCKS;
			break;
		case SCKS: {
			uint8_t expected = (uint8_t)(~sum);
			if (b != expected)
				return -3;
			return 0;
		}
		}
	}
	return -4;
}

static int smartbus_txrx(uart_port_t uart, const uint8_t *tx, int txlen,
                         smartbus_frame_t *rx, int timeout_ms) {
	if (uart >= UART_NUM_MAX)
		return -1;
	if (!g_smartbus_mu[uart])
		g_smartbus_mu[uart] = xSemaphoreCreateMutex();
	if (!g_smartbus_mu[uart])
		return -2;

	xSemaphoreTake(g_smartbus_mu[uart], portMAX_DELAY);

	uart_flush_input(uart);
	uart_write_bytes(uart, (const char *)tx, (size_t)txlen);
	uart_wait_tx_done(uart, pdMS_TO_TICKS(20));
	vTaskDelay(pdMS_TO_TICKS(1));

	int r = smartbus_read_frame(uart, rx, timeout_ms);

	xSemaphoreGive(g_smartbus_mu[uart]);
	return r;
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
	if (uart_port >= UART_NUM_MAX)
		return;
	if (!g_smart_buses[uart_port].configured)
		return;

	uint16_t pos = angle_to_position(angle_x10);
	uint16_t time_clamped = duration_ms;
	if (time_clamped > 30000)
		time_clamped = 30000;

	// Write goal position/time/speed starting at GOAL_POSITION_L.
	// Payload: addr, posL,posH, timeL,timeH, speedL,speedH
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
	if (plen <= 0)
		return;
	uart_write_bytes((uart_port_t)uart_port, (const char *)packet,
	                 (size_t)plen);
}

static void smartbus_write_bytes(uint8_t uart_port, uint8_t servo_id,
                                 uint8_t addr, const uint8_t *data,
                                 uint8_t data_len) {
	if (uart_port >= UART_NUM_MAX)
		return;
	if (!g_smart_buses[uart_port].configured)
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
	if (plen <= 0)
		return;
	uart_write_bytes((uart_port_t)uart_port, (const char *)packet,
	                 (size_t)plen);
}

void motor_hw_smartbus_set_mode(uint8_t uart_port, uint8_t servo_id,
                                uint8_t mode) {
	smartbus_write_bytes(uart_port, servo_id, (uint8_t)SMARTBUS_ADDR_MODE,
	                     &mode, 1);
}

void motor_hw_smartbus_set_wheel_speed(uint8_t uart_port, uint8_t servo_id,
                                       int16_t speed_raw, uint8_t acc) {
	uint8_t data[7];
	data[0] = acc;
	data[1] = 0;
	data[2] = 0;
	data[3] = 0;
	data[4] = 0;
	data[5] = (uint8_t)(speed_raw & 0xFF);
	data[6] = (uint8_t)((speed_raw >> 8) & 0xFF);
	smartbus_write_bytes(uart_port, servo_id, (uint8_t)SMARTBUS_ADDR_ACC, data,
	                     sizeof(data));
}

void motor_hw_smartbus_write_u8(uint8_t uart_port, uint8_t servo_id,
                                uint8_t addr, uint8_t value) {
	smartbus_write_bytes(uart_port, servo_id, addr, &value, 1);
}

int motor_hw_smartbus_read_position(uint8_t uart_port, uint8_t servo_id,
                                    uint16_t *pos_raw_out) {
	if (!pos_raw_out)
		return -1;
	if (uart_port >= UART_NUM_MAX)
		return -2;
	if (!g_smart_buses[uart_port].configured)
		return -3;

	// Read 2 bytes from PRESENT_POSITION_L.
	uint8_t params[2];
	params[0] = (uint8_t)SMARTBUS_ADDR_PRESENT_POSITION_L;
	params[1] = 2;
	uint8_t tx[16];
	int txlen =
	    smartbus_build(tx, sizeof(tx), servo_id, (uint8_t)SMARTBUS_INST_READ,
	                   params, sizeof(params));
	if (txlen < 0)
		return -4;

	smartbus_frame_t rx;
	int r = smartbus_txrx((uart_port_t)uart_port, tx, txlen, &rx, 50);
	if (r != 0)
		return r;

	if (rx.id != servo_id)
		return -5;
	if (rx.params_len < 2)
		return -6;

	*pos_raw_out = (uint16_t)(rx.params[0] | (rx.params[1] << 8));
	return 0;
}

int motor_hw_smartbus_ping(uint8_t uart_port, uint8_t servo_id,
                           int timeout_ms) {
	if (uart_port >= UART_NUM_MAX)
		return -1;
	if (!g_smart_buses[uart_port].configured)
		return -2;
	if (timeout_ms <= 0)
		timeout_ms = 50;

	uint8_t tx[16];
	int txlen = smartbus_build(tx, sizeof(tx), servo_id,
	                           (uint8_t)SMARTBUS_CMD_PING, NULL, 0);
	if (txlen < 0)
		return -3;

	smartbus_frame_t rx;
	int r = smartbus_txrx((uart_port_t)uart_port, tx, txlen, &rx, timeout_ms);
	if (r != 0)
		return r;
	if (rx.id != servo_id)
		return -4;
	return 0;
}

void motor_init(void) { motor_system_init(); }
