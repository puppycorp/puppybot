#include "driver/gpio.h"
#include "driver/ledc.h"


// ---------------- GPIO Definitions ----------------

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

// ---------------- GPIO Init ----------------

void motor_gpio_init() {
    gpio_config_t io_conf = {
        .pin_bit_mask = (1ULL << IN1_GPIO) | (1ULL << IN2_GPIO) |
                        (1ULL << IN3_GPIO) | (1ULL << IN4_GPIO) |
                        (1ULL << IN5_GPIO) | (1ULL << IN6_GPIO) |
                        (1ULL << IN7_GPIO) | (1ULL << IN8_GPIO),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE
    };
    gpio_config(&io_conf);
}

// ---------------- PWM Init ----------------

void motor_pwm_init() {
    ledc_timer_config_t ledc_timer = {
        .speed_mode = LEDC_MODE,
        .timer_num = LEDC_TIMER,
        .duty_resolution = LEDC_DUTY_RES,
        .freq_hz = LEDC_FREQUENCY,
        .clk_cfg = LEDC_AUTO_CLK
    };
    ledc_timer_config(&ledc_timer);

    ledc_channel_config_t channels[] = {
        { .speed_mode = LEDC_MODE, .channel = ENA_CHANNEL, .timer_sel = LEDC_TIMER,
          .intr_type = LEDC_INTR_DISABLE, .gpio_num = ENA_GPIO, .duty = 0, .hpoint = 0 },

        { .speed_mode = LEDC_MODE, .channel = ENB_CHANNEL, .timer_sel = LEDC_TIMER,
          .intr_type = LEDC_INTR_DISABLE, .gpio_num = ENB_GPIO, .duty = 0, .hpoint = 0 },

        { .speed_mode = LEDC_MODE, .channel = ENC_CHANNEL, .timer_sel = LEDC_TIMER,
          .intr_type = LEDC_INTR_DISABLE, .gpio_num = ENC_GPIO, .duty = 0, .hpoint = 0 },

        { .speed_mode = LEDC_MODE, .channel = END_CHANNEL, .timer_sel = LEDC_TIMER,
          .intr_type = LEDC_INTR_DISABLE, .gpio_num = END_GPIO, .duty = 0, .hpoint = 0 }
    };

    for (int i = 0; i < 4; i++) {
        ledc_channel_config(&channels[i]);
    }
}


// ---------------- Motor Control Functions ----------------

#define DEFINE_MOTOR_FUNCTIONS(NAME, INx, INy, CHANNEL) \
void NAME##_forward(uint8_t speed) { \
    gpio_set_level(INx, 1); \
    gpio_set_level(INy, 0); \
    ledc_set_duty(LEDC_MODE, CHANNEL, speed); \
    ledc_update_duty(LEDC_MODE, CHANNEL); \
} \
void NAME##_backward(uint8_t speed) { \
    gpio_set_level(INx, 0); \
    gpio_set_level(INy, 1); \
    ledc_set_duty(LEDC_MODE, CHANNEL, speed); \
    ledc_update_duty(LEDC_MODE, CHANNEL); \
} \
void NAME##_stop() { \
    gpio_set_level(INx, 0); \
    gpio_set_level(INy, 0); \
    ledc_set_duty(LEDC_MODE, CHANNEL, 0); \
    ledc_update_duty(LEDC_MODE, CHANNEL); \
}

// Create functions for each motor
DEFINE_MOTOR_FUNCTIONS(motorA, IN1_GPIO, IN2_GPIO, ENA_CHANNEL)
DEFINE_MOTOR_FUNCTIONS(motorB, IN3_GPIO, IN4_GPIO, ENB_CHANNEL)
DEFINE_MOTOR_FUNCTIONS(motorC, IN5_GPIO, IN6_GPIO, ENC_CHANNEL)
DEFINE_MOTOR_FUNCTIONS(motorD, IN7_GPIO, IN8_GPIO, END_CHANNEL)