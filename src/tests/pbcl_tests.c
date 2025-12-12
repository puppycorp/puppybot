#include "test.h"

#include "pbcl.h"

#include <stdint.h>
#include <string.h>

typedef struct {
	uint8_t data[256];
	size_t len;
} pbcl_buffer_t;

static void pbcl_buffer_append(pbcl_buffer_t *buf, const void *data,
                               size_t len) {
	memcpy(buf->data + buf->len, data, len);
	buf->len += len;
}

static pbcl_hdr_t *pbcl_buffer_header(pbcl_buffer_t *buf) {
	return (pbcl_hdr_t *)buf->data;
}

static pbcl_sec_t *pbcl_buffer_section(pbcl_buffer_t *buf, size_t index) {
	uint8_t *ptr = buf->data + sizeof(pbcl_hdr_t);
	uint8_t *end = buf->data + buf->len;
	size_t current = 0;
	while (ptr < end) {
		pbcl_sec_t *sec = (pbcl_sec_t *)ptr;
		if (current == index)
			return sec;
		ptr += sizeof(pbcl_sec_t) + sec->tlv_len;
		current++;
	}
	return NULL;
}

static void pbcl_buffer_finalize(pbcl_buffer_t *buf) {
	pbcl_hdr_t *hdr = pbcl_buffer_header(buf);
	hdr->total_size = (uint32_t)buf->len;
	pbcl_hdr_t header_copy = *hdr;
	header_copy.crc32 = 0;
	uint32_t crc = pbcl_crc32_init();
	crc = pbcl_crc32_update(crc, &header_copy, sizeof(header_copy));
	if (buf->len > sizeof(pbcl_hdr_t)) {
		crc = pbcl_crc32_update(crc, buf->data + sizeof(pbcl_hdr_t),
		                        buf->len - sizeof(pbcl_hdr_t));
	}
	hdr->crc32 = pbcl_crc32_finalize(crc);
}

static pbcl_buffer_t pbcl_make_sample_blob(void) {
	pbcl_buffer_t buf = {{0}, sizeof(pbcl_hdr_t)};
	pbcl_hdr_t *hdr = pbcl_buffer_header(&buf);
	hdr->magic = PBCL_MAGIC;
	hdr->version = PBCL_VERSION;
	hdr->reserved = 0;
	hdr->sections = 0;
	hdr->hdr_size = sizeof(pbcl_hdr_t);
	hdr->total_size = 0;
	hdr->crc32 = 0;

	/* Section 0 */
	size_t sec0_offset = buf.len;
	pbcl_sec_t sec0 = {PBCL_CLASS_MOTOR, 1, 0x10u, 0, 0};
	pbcl_buffer_append(&buf, &sec0, sizeof(sec0));
	size_t sec0_tlv_start = buf.len;
	pbcl_tlv_t name0 = {PBCL_T_NAME, 0, 4};
	pbcl_buffer_append(&buf, &name0, sizeof(name0));
	pbcl_buffer_append(&buf, "left", 4);
	pbcl_tlv_t end0 = {PBCL_T_END, 0, 0};
	pbcl_buffer_append(&buf, &end0, sizeof(end0));
	uint16_t sec0_tlv_len = (uint16_t)(buf.len - sec0_tlv_start);
	((pbcl_sec_t *)(buf.data + sec0_offset))->tlv_len = sec0_tlv_len;

	/* Section 1 */
	size_t sec1_offset = buf.len;
	pbcl_sec_t sec1 = {PBCL_CLASS_MOTOR, 2, 0x20u, 0, 0};
	pbcl_buffer_append(&buf, &sec1, sizeof(sec1));
	size_t sec1_tlv_start = buf.len;
	pbcl_tlv_t name1 = {PBCL_T_NAME, 0, 3};
	pbcl_buffer_append(&buf, &name1, sizeof(name1));
	pbcl_buffer_append(&buf, "arm", 3);
	pbcl_tlv_t timeout = {PBCL_T_TIMEOUT, 0, 2};
	uint16_t timeout_val = 1500;
	pbcl_buffer_append(&buf, &timeout, sizeof(timeout));
	pbcl_buffer_append(&buf, &timeout_val, sizeof(timeout_val));
	pbcl_tlv_t end1 = {PBCL_T_END, 0, 0};
	pbcl_buffer_append(&buf, &end1, sizeof(end1));
	uint16_t sec1_tlv_len = (uint16_t)(buf.len - sec1_tlv_start);
	((pbcl_sec_t *)(buf.data + sec1_offset))->tlv_len = sec1_tlv_len;

	hdr->sections = 2;
	pbcl_buffer_finalize(&buf);
	return buf;
}

TEST(pbcl_parse_valid_blob) {
	pbcl_buffer_t blob = pbcl_make_sample_blob();
	pbcl_doc_t doc;
	pbcl_status_t st = pbcl_parse(blob.data, blob.len, &doc);
	ASSERT_EQ(st, PBCL_OK);
	ASSERT_EQ(pbcl_doc_section_count(&doc), 2u);

	const pbcl_sec_t *sec0 = pbcl_doc_first_section(&doc);
	ASSERT(sec0 != NULL);
	ASSERT_EQ(sec0->node_id, 0x10u);

	pbcl_tlv_iter_t iter = pbcl_tlv_iter_init(&doc, sec0);
	pbcl_tlv_view_t view;
	ASSERT(pbcl_tlv_next(&iter, &view));
	ASSERT_EQ(view.tlv->tag, PBCL_T_NAME);
	ASSERT_EQ(view.tlv->len, 4u);
	ASSERT(memcmp(view.value, "left", 4) == 0);
	ASSERT(pbcl_tlv_next(&iter, &view));
	ASSERT_EQ(view.tlv->tag, PBCL_T_END);
	ASSERT(!pbcl_tlv_next(&iter, &view));

	const pbcl_sec_t *sec1 = pbcl_doc_next_section(&doc, sec0);
	ASSERT(sec1 != NULL);
	ASSERT_EQ(sec1->node_id, 0x20u);

	pbcl_tlv_iter_t iter1 = pbcl_tlv_iter_init(&doc, sec1);
	ASSERT(pbcl_tlv_next(&iter1, &view));
	ASSERT_EQ(view.tlv->tag, PBCL_T_NAME);
	ASSERT_EQ(view.tlv->len, 3u);
	ASSERT(memcmp(view.value, "arm", 3) == 0);
	ASSERT(pbcl_tlv_next(&iter1, &view));
	ASSERT_EQ(view.tlv->tag, PBCL_T_TIMEOUT);
	ASSERT_EQ(view.tlv->len, 2u);
	uint16_t timeout_val = 0;
	memcpy(&timeout_val, view.value, sizeof(timeout_val));
	ASSERT_EQ(timeout_val, (uint16_t)1500);
	ASSERT(pbcl_tlv_next(&iter1, &view));
	ASSERT_EQ(view.tlv->tag, PBCL_T_END);
	ASSERT(!pbcl_tlv_next(&iter1, &view));

	ASSERT(pbcl_doc_next_section(&doc, sec1) == NULL);
}

TEST(pbcl_parse_detects_crc_mismatch) {
	pbcl_buffer_t blob = pbcl_make_sample_blob();
	blob.data[sizeof(pbcl_hdr_t) + sizeof(pbcl_sec_t) + sizeof(pbcl_tlv_t)] ^=
	    0xFFu;
	pbcl_doc_t doc;
	ASSERT_EQ(pbcl_parse(blob.data, blob.len, &doc), PBCL_ERR_BAD_CRC);
}

TEST(pbcl_parse_rejects_tlv_truncation) {
	pbcl_buffer_t blob = pbcl_make_sample_blob();
	pbcl_sec_t *sec0 = pbcl_buffer_section(&blob, 0);
	ASSERT(sec0 != NULL);
	if (sec0->tlv_len > 0)
		sec0->tlv_len -= 1;
	pbcl_buffer_finalize(&blob);
	pbcl_doc_t doc;
	ASSERT_EQ(pbcl_parse(blob.data, blob.len, &doc), PBCL_ERR_TLV_BOUNDS);
}

TEST(pbcl_parse_validates_section_count) {
	pbcl_buffer_t blob = pbcl_make_sample_blob();
	pbcl_hdr_t *hdr = pbcl_buffer_header(&blob);
	hdr->sections = 3;
	pbcl_buffer_finalize(&blob);
	pbcl_doc_t doc;
	ASSERT_EQ(pbcl_parse(blob.data, blob.len, &doc), PBCL_ERR_SECTION_COUNT);
}

TEST(pbcl_parse_rejects_bad_magic) {
	pbcl_buffer_t blob = pbcl_make_sample_blob();
	pbcl_hdr_t *hdr = pbcl_buffer_header(&blob);
	hdr->magic = 0;
	pbcl_doc_t doc;
	ASSERT_EQ(pbcl_parse(blob.data, blob.len, &doc), PBCL_ERR_BAD_MAGIC);
}
