#ifndef ESPIDF_STUBS_H
#define ESPIDF_STUBS_H

#ifndef ESP_PLATFORM

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum {
	GPIO_NUM_0 = 0,
	GPIO_NUM_1,
	GPIO_NUM_2,
	GPIO_NUM_3,
	GPIO_NUM_4,
	GPIO_NUM_5,
	GPIO_NUM_6,
	GPIO_NUM_7,
	GPIO_NUM_8,
	GPIO_NUM_9,
	GPIO_NUM_10,
	GPIO_NUM_11,
	GPIO_NUM_12,
	GPIO_NUM_13,
	GPIO_NUM_14,
	GPIO_NUM_15,
	GPIO_NUM_16,
	GPIO_NUM_17,
	GPIO_NUM_18,
	GPIO_NUM_19,
	GPIO_NUM_20,
	GPIO_NUM_21,
	GPIO_NUM_22,
	GPIO_NUM_23,
	GPIO_NUM_24,
	GPIO_NUM_25,
	GPIO_NUM_26,
	GPIO_NUM_27,
	GPIO_NUM_28,
	GPIO_NUM_29,
	GPIO_NUM_30,
	GPIO_NUM_31,
	GPIO_NUM_32,
	GPIO_NUM_33,
	GPIO_NUM_34,
	GPIO_NUM_35,
	GPIO_NUM_36,
	GPIO_NUM_37,
	GPIO_NUM_38,
	GPIO_NUM_39,
	GPIO_NUM_MAX
} gpio_num_t;

typedef enum {
	GPIO_MODE_DISABLE = 0x0,
	GPIO_MODE_INPUT = 0x1,
	GPIO_MODE_OUTPUT = 0x2,
	GPIO_MODE_OUTPUT_OD = 0x4,
	GPIO_MODE_INPUT_OUTPUT = GPIO_MODE_INPUT | GPIO_MODE_OUTPUT,
	GPIO_MODE_INPUT_OUTPUT_OD = GPIO_MODE_INPUT | GPIO_MODE_OUTPUT_OD
} gpio_mode_t;

typedef enum {
	GPIO_PULLUP_DISABLE = 0,
	GPIO_PULLUP_ENABLE = 1,
} gpio_pullup_t;

typedef enum {
	GPIO_PULLDOWN_DISABLE = 0,
	GPIO_PULLDOWN_ENABLE = 1,
} gpio_pulldown_t;

typedef enum {
	GPIO_INTR_DISABLE = 0,
} gpio_int_type_t;

typedef struct {
	uint64_t pin_bit_mask;
	gpio_mode_t mode;
	gpio_pullup_t pull_up_en;
	gpio_pulldown_t pull_down_en;
	gpio_int_type_t intr_type;
} gpio_config_t;

typedef enum {
	LEDC_TIMER_0 = 0,
	LEDC_TIMER_1,
	LEDC_TIMER_2,
	LEDC_TIMER_3,
	LEDC_TIMER_MAX
} ledc_timer_t;

typedef enum {
	LEDC_HIGH_SPEED_MODE = 0,
	LEDC_LOW_SPEED_MODE = 1,
	LEDC_SPEED_MODE_MAX
} ledc_mode_t;

typedef enum {
	LEDC_CHANNEL_0 = 0,
	LEDC_CHANNEL_1,
	LEDC_CHANNEL_2,
	LEDC_CHANNEL_3,
	LEDC_CHANNEL_4,
	LEDC_CHANNEL_5,
	LEDC_CHANNEL_6,
	LEDC_CHANNEL_7,
	LEDC_CHANNEL_MAX
} ledc_channel_t;

typedef enum {
	LEDC_TIMER_1_BIT = 1,
	LEDC_TIMER_2_BIT,
	LEDC_TIMER_3_BIT,
	LEDC_TIMER_4_BIT,
	LEDC_TIMER_5_BIT,
	LEDC_TIMER_6_BIT,
	LEDC_TIMER_7_BIT,
	LEDC_TIMER_8_BIT,
	LEDC_TIMER_9_BIT,
	LEDC_TIMER_10_BIT,
	LEDC_TIMER_11_BIT,
	LEDC_TIMER_12_BIT,
	LEDC_TIMER_13_BIT,
	LEDC_TIMER_14_BIT,
	LEDC_TIMER_15_BIT,
	LEDC_TIMER_16_BIT
} ledc_timer_bit_t;

typedef enum {
	LEDC_INTR_DISABLE = 0,
} ledc_intr_type_t;

typedef enum {
	LEDC_AUTO_CLK = 0,
} ledc_clk_cfg_t;

typedef int esp_err_t;

#define ESP_OK 0

typedef struct {
	ledc_mode_t speed_mode;
	ledc_timer_t timer_num;
	ledc_timer_bit_t duty_resolution;
	uint32_t freq_hz;
	ledc_clk_cfg_t clk_cfg;
} ledc_timer_config_t;

typedef struct {
	ledc_mode_t speed_mode;
	ledc_channel_t channel;
	ledc_timer_t timer_sel;
	ledc_intr_type_t intr_type;
	gpio_num_t gpio_num;
	uint32_t duty;
	int hpoint;
} ledc_channel_config_t;

typedef struct {
	bool called;
	size_t call_count;
	gpio_config_t config;
} gpio_config_call_t;

typedef struct {
	bool called;
	size_t call_count;
	ledc_timer_config_t config;
} ledc_timer_config_call_t;

typedef struct {
	bool called;
	size_t call_count;
	ledc_channel_config_t config;
} ledc_channel_config_call_t;

typedef struct {
	bool called;
	size_t call_count;
	ledc_mode_t mode;
	ledc_channel_t channel;
	uint32_t duty;
} ledc_set_duty_call_t;

typedef struct {
	bool called;
	size_t call_count;
	ledc_mode_t mode;
	ledc_channel_t channel;
} ledc_update_duty_call_t;

typedef struct {
	bool called;
	size_t call_count;
	gpio_num_t gpio;
	int level;
} gpio_set_level_call_t;

extern gpio_config_call_t gpio_config_last_call;
extern ledc_timer_config_call_t ledc_timer_config_last_call;
extern ledc_channel_config_call_t ledc_channel_config_last_call;
extern ledc_set_duty_call_t ledc_set_duty_last_call;
extern ledc_update_duty_call_t ledc_update_duty_last_call;
extern gpio_set_level_call_t gpio_set_level_last_call;

void espidf_stubs_reset(void);
esp_err_t gpio_config(const gpio_config_t *config);
esp_err_t ledc_timer_config(const ledc_timer_config_t *config);
esp_err_t ledc_channel_config(const ledc_channel_config_t *config);
esp_err_t ledc_set_duty(ledc_mode_t speed_mode, ledc_channel_t channel,
                        uint32_t duty);
esp_err_t ledc_update_duty(ledc_mode_t speed_mode, ledc_channel_t channel);
esp_err_t gpio_set_level(gpio_num_t gpio, int level);

#endif // ESP_PLATFORM

#endif // ESPIDF_STUBS_H
