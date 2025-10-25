#include "pbcl_motor_handler.h"

#include <string.h>

#include "motor_slots.h"
#include "pbcl_tags.h"

typedef struct {
	const uint8_t *p;
	size_t rem;
} tlv_span_t;

static int tlv_next(tlv_span_t *s, pbcl_tlv_t *out, const uint8_t **val) {
	if (!s || !out || !val)
		return 0;
	if (s->rem < sizeof(pbcl_tlv_t))
		return 0;
	const pbcl_tlv_t *t = (const pbcl_tlv_t *)s->p;
	size_t need = sizeof(pbcl_tlv_t) + t->len;
	if (s->rem < need)
		return 0;
	memcpy(out, t, sizeof(*out));
	*val = s->p + sizeof(*out);
	s->p += need;
	s->rem -= need;
	return 1;
}

int pbcl_apply_motor_section(const pbcl_sec_t *sec, const uint8_t *tlvs,
                             size_t len) {
	if (!sec || !tlvs)
		return -1;

	motor_rt_t m;
	memset(&m, 0, sizeof(m));
	m.node_id = sec->node_id;
	m.type_id = sec->type_id;
	m.pwm_freq = 50;
	m.deg_min_x10 = 0;
	m.deg_max_x10 = 1800;

	tlv_span_t span = {tlvs, len};
	pbcl_tlv_t t;
	const uint8_t *v = NULL;

	while (tlv_next(&span, &t, &v)) {
		switch (t.tag) {
		case PBCL_T_NAME: {
			size_t n = t.len < sizeof(m.name) - 1 ? t.len : sizeof(m.name) - 1;
			memcpy(m.name, v, n);
			m.name[n] = '\0';
		} break;
		case PBCL_T_TIMEOUT:
			if (t.len == 2)
				m.timeout_ms = *(const uint16_t *)v;
			break;
		case PBCL_T_M_PWM:
			if (t.len == sizeof(pbcl_t_motor_pwm)) {
				const pbcl_t_motor_pwm *pw = (const pbcl_t_motor_pwm *)v;
				m.pwm_pin = pw->pin;
				m.pwm_ch = pw->ch;
				m.pwm_freq = pw->freq_hz;
				m.min_us = pw->min_us;
				m.max_us = pw->max_us;
				m.neutral_us = pw->neutral_us;
				m.invert = pw->invert;
			}
			break;
		case PBCL_T_M_HBRIDGE:
			if (t.len == sizeof(pbcl_t_motor_hbridge)) {
				const pbcl_t_motor_hbridge *hb =
				    (const pbcl_t_motor_hbridge *)v;
				m.in1_pin = hb->in1;
				m.in2_pin = hb->in2;
				m.brake_mode = hb->brake_mode;
			}
			break;
		case PBCL_T_M_ANALOG_FB:
			if (t.len == sizeof(pbcl_t_motor_analogfb)) {
				const pbcl_t_motor_analogfb *af =
				    (const pbcl_t_motor_analogfb *)v;
				m.adc_pin = af->adc_pin;
				m.adc_min = af->adc_min;
				m.adc_max = af->adc_max;
				m.deg_min_x10 = af->deg_min_x10;
				m.deg_max_x10 = af->deg_max_x10;
			}
			break;
		case PBCL_T_M_LIMITS:
			if (t.len == sizeof(pbcl_t_motor_limits)) {
				const pbcl_t_motor_limits *lm = (const pbcl_t_motor_limits *)v;
				m.max_speed_x100 = lm->max_speed_x100;
			}
			break;
		default:
			break;
		}
	}

	if (m.type_id == MOTOR_TYPE_HBR) {
		if (m.pwm_pin < 0 || m.in1_pin < 0 || m.in2_pin < 0)
			return -2;
		if (m.pwm_freq == 0)
			m.pwm_freq = 1000;
	} else if (m.type_id == MOTOR_TYPE_CONT) {
		if (m.pwm_pin < 0 || m.neutral_us == 0)
			return -2;
		if (!m.min_us)
			m.min_us = 1000;
		if (!m.max_us)
			m.max_us = 2000;
	} else if (m.type_id == MOTOR_TYPE_ANGLE) {
		if (m.pwm_pin < 0 || !m.min_us || !m.max_us)
			return -2;
	}

	int rc = motor_registry_add(&m);
	if (rc != 0)
		return rc;

	motor_rt_t *stored = NULL;
	if (motor_registry_find(m.node_id, &stored) == 0 && stored)
		motor_slots_register(stored);

	return 0;
}
