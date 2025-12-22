#include "motor_config.h"
#include "pbcl.h"
#include "pbcl_tags.h"
#include "test.h"

#include <stdlib.h>
#include <string.h>

typedef struct {
	uint8_t *blob;
	size_t blob_len;
	int load_result;
	int store_result;
	size_t store_calls;
} config_stub_t;

static config_stub_t g_config_stub;

static void config_stub_reset(void) {
	if (g_config_stub.blob) {
		free(g_config_stub.blob);
	}
	memset(&g_config_stub, 0, sizeof(g_config_stub));
	g_config_stub.load_result = 1;
}

int platform_store_config_blob(const uint8_t *data, size_t len) {
	g_config_stub.store_calls++;
	if (g_config_stub.store_result != 0) {
		return g_config_stub.store_result;
	}
	free(g_config_stub.blob);
	g_config_stub.blob = NULL;
	g_config_stub.blob_len = 0;
	if (!data || len == 0) {
		return -1;
	}
	g_config_stub.blob = (uint8_t *)malloc(len);
	if (!g_config_stub.blob) {
		return -1;
	}
	memcpy(g_config_stub.blob, data, len);
	g_config_stub.blob_len = len;
	return 0;
}

int platform_load_config_blob(uint8_t **out_data, size_t *out_len) {
	if (!out_data || !out_len) {
		return -1;
	}
	*out_data = NULL;
	*out_len = 0;
	if (g_config_stub.load_result != 0) {
		return g_config_stub.load_result;
	}
	if (!g_config_stub.blob || g_config_stub.blob_len == 0) {
		return 1;
	}
	uint8_t *copy = (uint8_t *)malloc(g_config_stub.blob_len);
	if (!copy) {
		return -1;
	}
	memcpy(copy, g_config_stub.blob, g_config_stub.blob_len);
	*out_data = copy;
	*out_len = g_config_stub.blob_len;
	return 0;
}

void platform_free_config_blob(uint8_t *data) { free(data); }

typedef struct {
	uint8_t data[128];
	size_t len;
} pbcl_buffer_t;

static void pbcl_append(pbcl_buffer_t *buf, const void *data, size_t len) {
	memcpy(buf->data + buf->len, data, len);
	buf->len += len;
}

static pbcl_buffer_t make_sample_blob(void) {
	pbcl_buffer_t buf = {{0}, sizeof(pbcl_hdr_t)};
	pbcl_hdr_t *hdr = (pbcl_hdr_t *)buf.data;
	hdr->magic = PBCL_MAGIC;
	hdr->version = PBCL_VERSION;
	hdr->sections = 1;
	hdr->hdr_size = sizeof(pbcl_hdr_t);

	pbcl_sec_t sec = {PBCL_CLASS_MOTOR, PBCL_MOTOR_TYPE_ANGLE, 1, 0, 0};
	size_t sec_offset = buf.len;
	pbcl_append(&buf, &sec, sizeof(sec));

	pbcl_t_motor_pwm pwm = {
	    .pin = 2,
	    .ch = 0,
	    .freq_hz = 50,
	    .min_us = 1000,
	    .max_us = 2000,
	    .neutral_us = 1500,
	    .invert = 0,
	    .reserved = 0,
	};
	pbcl_tlv_t pwm_tlv = {PBCL_T_M_PWM, 0, sizeof(pwm)};
	pbcl_append(&buf, &pwm_tlv, sizeof(pwm_tlv));
	pbcl_append(&buf, &pwm, sizeof(pwm));

	((pbcl_sec_t *)(buf.data + sec_offset))->tlv_len =
	    (uint16_t)(buf.len - sec_offset - sizeof(pbcl_sec_t));

	hdr->total_size = (uint32_t)buf.len;
	pbcl_hdr_t header_copy = *hdr;
	header_copy.crc32 = 0;
	uint32_t crc = pbcl_crc32_init();
	crc = pbcl_crc32_update(crc, &header_copy, sizeof(header_copy));
	if (buf.len > sizeof(pbcl_hdr_t)) {
		crc = pbcl_crc32_update(crc, buf.data + sizeof(pbcl_hdr_t),
		                        buf.len - sizeof(pbcl_hdr_t));
	}
	hdr->crc32 = pbcl_crc32_finalize(crc);
	return buf;
}

TEST(motor_config_persist_active_stores_blob) {
	config_stub_reset();
	pbcl_buffer_t blob = make_sample_blob();
	ASSERT_EQ(motor_config_apply_blob(blob.data, blob.len), 0);
	ASSERT_EQ(motor_config_persist_active(), 0);
	ASSERT_EQ(g_config_stub.store_calls, (size_t)1);
	ASSERT_EQ(g_config_stub.blob_len, blob.len);
	ASSERT(memcmp(g_config_stub.blob, blob.data, blob.len) == 0);
	motor_config_reset();
}

TEST(motor_system_init_uses_stored_blob) {
	config_stub_reset();
	motor_config_reset();
	pbcl_buffer_t blob = make_sample_blob();
	g_config_stub.blob = (uint8_t *)malloc(blob.len);
	memcpy(g_config_stub.blob, blob.data, blob.len);
	g_config_stub.blob_len = blob.len;
	g_config_stub.load_result = 0;

	ASSERT_EQ(motor_system_init(), 0);

	const uint8_t *active = NULL;
	size_t active_len = 0;
	if (motor_config_get_active_blob(&active, &active_len) != 0) {
		ASSERT(0);
		motor_system_shutdown();
		return;
	}
	ASSERT_EQ(active_len, blob.len);
	ASSERT(memcmp(active, blob.data, blob.len) == 0);
	motor_system_shutdown();
}
