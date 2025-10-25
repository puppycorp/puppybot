#include "motor_runtime.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "motor_hw.h"

#define MAX_MOTORS 16

static motor_rt_t g_motors[MAX_MOTORS];
static int g_mcount = 0;
static const motor_hw_ops_t *g_hw_ops = NULL;

static inline const motor_hw_ops_t *hw_ops(void) {
        if (!g_hw_ops)
                g_hw_ops = motor_hw_default_ops();
        return g_hw_ops;
}

void motor_runtime_set_hw_ops(const motor_hw_ops_t *ops) { g_hw_ops = ops; }

const motor_hw_ops_t *motor_runtime_get_hw_ops(void) { return hw_ops(); }

static inline uint32_t current_time_ms(void) {
        const motor_hw_ops_t *ops = hw_ops();
        return ops && ops->now_ms ? ops->now_ms() : 0;
}

int motor_registry_add(const motor_rt_t *m) {
        if (!m)
                return -1;
        if (g_mcount >= MAX_MOTORS)
                return -2;
        g_motors[g_mcount] = *m;
        g_motors[g_mcount].last_cmd_ms = current_time_ms();
        g_motors[g_mcount].last_cmd_val = 0.0f;
        g_mcount++;
        return 0;
}

int motor_registry_find(uint32_t node_id, motor_rt_t **out) {
        if (!out)
                return -1;
        for (int i = 0; i < g_mcount; ++i) {
                if (g_motors[i].node_id == node_id) {
                        *out = &g_motors[i];
                        return 0;
                }
        }
        return -2;
}

void motor_registry_clear(void) {
        memset(g_motors, 0, sizeof(g_motors));
        g_mcount = 0;
}

int motor_count(void) { return g_mcount; }

motor_rt_t *motor_at(int idx) {
        if (idx < 0 || idx >= g_mcount)
                return NULL;
        return &g_motors[idx];
}

int motor_hw_init(void) {
        const motor_hw_ops_t *ops = hw_ops();
        if (ops && ops->init)
                return ops->init();
        return 0;
}

static void apply_continuous_servo(motor_rt_t *m, float speed) {
        if (!m)
                return;
        if (m->invert)
                speed = -speed;
        if (m->max_speed_x100) {
                float cap = m->max_speed_x100 / 100.0f;
                if (speed > cap)
                        speed = cap;
                if (speed < -cap)
                        speed = -cap;
        }
        uint16_t span = (uint16_t)((m->max_us - m->min_us) / 2);
        int32_t us = (int32_t)m->neutral_us + (int32_t)(speed * (int32_t)span);
        if (us < m->min_us)
                us = m->min_us;
        if (us > m->max_us)
                us = m->max_us;

        const motor_hw_ops_t *ops = hw_ops();
        if (ops->ensure_pwm)
                ops->ensure_pwm(m->pwm_ch, m->pwm_freq);
        if (ops->bind_pwm_pin)
                ops->bind_pwm_pin(m->pwm_ch, m->pwm_pin);
        if (ops->set_pwm_pulse_us)
                ops->set_pwm_pulse_us(m->pwm_ch, m->pwm_freq, (uint16_t)us);
}

static void apply_angle_servo(motor_rt_t *m, float deg) {
        if (!m)
                return;
        float dmin = m->deg_min_x10 / 10.0f;
        float dmax = m->deg_max_x10 / 10.0f;
        if (deg < dmin)
                deg = dmin;
        if (deg > dmax)
                deg = dmax;
        float range = dmax - dmin;
        if (range < 1e-6f)
                range = 1e-6f;
        float t = (deg - dmin) / range;
        uint16_t us = (uint16_t)(m->min_us + t * (m->max_us - m->min_us));

        const motor_hw_ops_t *ops = hw_ops();
        if (ops->ensure_pwm)
                ops->ensure_pwm(m->pwm_ch, m->pwm_freq);
        if (ops->bind_pwm_pin)
                ops->bind_pwm_pin(m->pwm_ch, m->pwm_pin);
        if (ops->set_pwm_pulse_us)
                ops->set_pwm_pulse_us(m->pwm_ch, m->pwm_freq, us);
}

static void apply_hbridge_dc(motor_rt_t *m, float speed) {
        if (!m)
                return;
        if (m->invert)
                speed = -speed;
        if (speed > 1.f)
                speed = 1.f;
        if (speed < -1.f)
                speed = -1.f;

        const motor_hw_ops_t *ops = hw_ops();
        if (ops->configure_hbridge)
                ops->configure_hbridge(m->in1_pin, m->in2_pin, speed >= 0.f,
                                       m->brake_mode != 0);
        if (ops->ensure_pwm)
                ops->ensure_pwm(m->pwm_ch, m->pwm_freq);
        if (ops->bind_pwm_pin)
                ops->bind_pwm_pin(m->pwm_ch, m->pwm_pin);
        if (ops->set_pwm_duty)
                ops->set_pwm_duty(m->pwm_ch, fabsf(speed));
}

int motor_set_speed(uint32_t node_id, float speed) {
        motor_rt_t *m = NULL;
        if (motor_registry_find(node_id, &m) != 0 || !m)
                return -1;
        switch (m->type_id) {
        case MOTOR_TYPE_CONT:
                apply_continuous_servo(m, speed);
                break;
        case MOTOR_TYPE_HBR:
                apply_hbridge_dc(m, speed);
                break;
        default:
                return -2;
        }
        m->last_cmd_val = speed;
        m->last_cmd_ms = current_time_ms();
        return 0;
}

int motor_set_angle(uint32_t node_id, float deg) {
        motor_rt_t *m = NULL;
        if (motor_registry_find(node_id, &m) != 0 || !m)
                return -1;
        if (m->type_id != MOTOR_TYPE_ANGLE)
                return -2;
        apply_angle_servo(m, deg);
        m->last_cmd_val = deg;
        m->last_cmd_ms = current_time_ms();
        return 0;
}

int motor_stop(uint32_t node_id) {
        motor_rt_t *m = NULL;
        if (motor_registry_find(node_id, &m) != 0 || !m)
                return -1;
        const motor_hw_ops_t *ops = hw_ops();
        if (m->type_id == MOTOR_TYPE_CONT && m->neutral_us) {
                if (ops->ensure_pwm)
                        ops->ensure_pwm(m->pwm_ch, m->pwm_freq);
                if (ops->bind_pwm_pin)
                        ops->bind_pwm_pin(m->pwm_ch, m->pwm_pin);
                if (ops->set_pwm_pulse_us)
                        ops->set_pwm_pulse_us(m->pwm_ch, m->pwm_freq,
                                              m->neutral_us);
                m->last_cmd_val = 0.0f;
        } else if (m->type_id == MOTOR_TYPE_HBR) {
                if (ops->ensure_pwm)
                        ops->ensure_pwm(m->pwm_ch, m->pwm_freq);
                if (ops->bind_pwm_pin)
                        ops->bind_pwm_pin(m->pwm_ch, m->pwm_pin);
                if (ops->configure_hbridge)
                        ops->configure_hbridge(m->in1_pin, m->in2_pin, true, false);
                if (ops->set_pwm_duty)
                        ops->set_pwm_duty(m->pwm_ch, 0.0f);
                m->last_cmd_val = 0.0f;
        } else if (m->type_id == MOTOR_TYPE_ANGLE) {
                apply_angle_servo(m, m->last_cmd_val);
        }
        m->last_cmd_ms = current_time_ms();
        return 0;
}

void motor_tick_all(uint32_t now_ms_val) {
        const motor_hw_ops_t *ops = hw_ops();
        for (int i = 0; i < g_mcount; ++i) {
                motor_rt_t *m = &g_motors[i];
                if (m->timeout_ms == 0)
                        continue;
                if ((uint32_t)(now_ms_val - m->last_cmd_ms) > m->timeout_ms) {
                        if (m->type_id == MOTOR_TYPE_CONT && m->neutral_us) {
                                if (ops->ensure_pwm)
                                        ops->ensure_pwm(m->pwm_ch, m->pwm_freq);
                                if (ops->bind_pwm_pin)
                                        ops->bind_pwm_pin(m->pwm_ch, m->pwm_pin);
                                if (ops->set_pwm_pulse_us)
                                        ops->set_pwm_pulse_us(m->pwm_ch, m->pwm_freq,
                                                              m->neutral_us);
                                m->last_cmd_val = 0.0f;
                        } else if (m->type_id == MOTOR_TYPE_HBR) {
                                if (ops->ensure_pwm)
                                        ops->ensure_pwm(m->pwm_ch, m->pwm_freq);
                                if (ops->bind_pwm_pin)
                                        ops->bind_pwm_pin(m->pwm_ch, m->pwm_pin);
                                if (ops->configure_hbridge)
                                        ops->configure_hbridge(m->in1_pin, m->in2_pin,
                                                               true, false);
                                if (ops->set_pwm_duty)
                                        ops->set_pwm_duty(m->pwm_ch, 0.0f);
                                m->last_cmd_val = 0.0f;
                        }
                        m->last_cmd_ms = now_ms_val;
                }
        }
}
