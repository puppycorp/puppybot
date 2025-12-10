#include "../../src/motor_hw.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/uart.h"
#include "esp_log.h"
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

	uint8_t packet[10];
	memset(packet, 0, sizeof(packet));
	packet[0] = 0x55;
	packet[1] = 0x55;
	packet[2] = servo_id;
	packet[3] = 7; // length (params + 3)
	packet[4] = 1; // move command
	packet[5] = (uint8_t)(pos & 0xFFu);
	packet[6] = (uint8_t)((pos >> 8) & 0xFFu);
	packet[7] = (uint8_t)(time_clamped & 0xFFu);
	packet[8] = (uint8_t)((time_clamped >> 8) & 0xFFu);
	packet[9] = smart_checksum(packet, sizeof(packet));

	uart_write_bytes((uart_port_t)uart_port, (const char *)packet,
	                 sizeof(packet));
}
