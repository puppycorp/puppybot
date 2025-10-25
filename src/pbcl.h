#ifndef PBCL_H
#define PBCL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define PBCL_MAGIC 0x5042434Cu
#define PBCL_VERSION 1

typedef enum {
	PBCL_OK = 0,
	PBCL_ERR_INVALID_ARGUMENT = -1,
	PBCL_ERR_TRUNCATED = -2,
	PBCL_ERR_BAD_MAGIC = -3,
	PBCL_ERR_UNSUPPORTED_VERSION = -4,
	PBCL_ERR_BAD_HEADER_SIZE = -5,
	PBCL_ERR_SIZE_MISMATCH = -6,
	PBCL_ERR_BAD_CRC = -7,
	PBCL_ERR_SECTION_BOUNDS = -8,
	PBCL_ERR_TLV_BOUNDS = -9,
	PBCL_ERR_SECTION_COUNT = -10
} pbcl_status_t;

typedef struct __attribute__((packed)) {
	uint32_t magic;
	uint16_t version;
	uint16_t reserved;
	uint16_t sections;
	uint16_t hdr_size;
	uint32_t total_size;
	uint32_t crc32;
} pbcl_hdr_t;

typedef enum : uint16_t {
	PBCL_CLASS_MOTOR = 1,
	PBCL_CLASS_SENSOR = 2,
	PBCL_CLASS_POWER = 3,
	PBCL_CLASS_NETWORK = 4,
	PBCL_CLASS_IO = 5,
	PBCL_CLASS_LOGIC = 6,
	PBCL_CLASS_META = 255
} pbcl_class_t;

typedef struct __attribute__((packed)) {
	uint16_t class_id;
	uint16_t type_id;
	uint32_t node_id;
	uint16_t tlv_len;
	uint16_t reserved;
} pbcl_sec_t;

typedef struct __attribute__((packed)) {
	uint8_t tag;
	uint8_t flags;
	uint16_t len;
} pbcl_tlv_t;

enum {
	PBCL_T_NAME = 1,
	PBCL_T_DESC = 2,
	PBCL_T_TIMEOUT = 3,
	PBCL_T_FLAGS = 4,
	PBCL_T_DEPENDS = 5,
	PBCL_T_END = 255
};

typedef struct {
	const uint8_t *data;
	size_t length;
	const pbcl_hdr_t *header;
	const uint8_t *section_begin;
	const uint8_t *section_end;
	uint16_t section_count;
} pbcl_doc_t;

typedef struct {
	const uint8_t *cursor;
	const uint8_t *end;
} pbcl_tlv_iter_t;

typedef struct {
	const pbcl_tlv_t *tlv;
	const uint8_t *value;
} pbcl_tlv_view_t;

static inline uint32_t pbcl_crc32_init(void) { return 0xFFFFFFFFu; }

static inline uint32_t pbcl_crc32_update(uint32_t crc, const void *data,
                                         size_t len) {
	const uint8_t *p = (const uint8_t *)data;
	while (len--) {
		crc ^= *p++;
		for (int i = 0; i < 8; ++i) {
			crc = (crc >> 1) ^ (0xEDB88320u & (-(int)(crc & 1)));
		}
	}
	return crc;
}

static inline uint32_t pbcl_crc32_finalize(uint32_t crc) {
	return crc ^ 0xFFFFFFFFu;
}

static inline void pbcl_doc_reset(pbcl_doc_t *doc) {
	if (doc) {
		memset(doc, 0, sizeof(*doc));
	}
}

static inline pbcl_status_t pbcl_parse(const uint8_t *data, size_t len,
                                       pbcl_doc_t *out) {
	if (!data || !out)
		return PBCL_ERR_INVALID_ARGUMENT;

	pbcl_doc_reset(out);

	if (len < sizeof(pbcl_hdr_t))
		return PBCL_ERR_TRUNCATED;

	const pbcl_hdr_t *hdr = (const pbcl_hdr_t *)data;
	if (hdr->magic != PBCL_MAGIC)
		return PBCL_ERR_BAD_MAGIC;
	if (hdr->version != PBCL_VERSION)
		return PBCL_ERR_UNSUPPORTED_VERSION;
	if (hdr->hdr_size != sizeof(pbcl_hdr_t))
		return PBCL_ERR_BAD_HEADER_SIZE;
	if (hdr->total_size != len || hdr->total_size < hdr->hdr_size)
		return PBCL_ERR_SIZE_MISMATCH;

	pbcl_hdr_t header_copy = *hdr;
	header_copy.crc32 = 0;
	uint32_t crc = pbcl_crc32_init();
	crc = pbcl_crc32_update(crc, &header_copy, sizeof(header_copy));
	if (len > sizeof(pbcl_hdr_t)) {
		crc = pbcl_crc32_update(crc, data + sizeof(pbcl_hdr_t),
		                        len - sizeof(pbcl_hdr_t));
	}
	crc = pbcl_crc32_finalize(crc);
	if (crc != hdr->crc32)
		return PBCL_ERR_BAD_CRC;

	const uint8_t *section_ptr = data + hdr->hdr_size;
	const uint8_t *const section_end = data + len;
	uint16_t sections_seen = 0;

	while (section_ptr < section_end) {
		size_t remaining = (size_t)(section_end - section_ptr);
		if (remaining < sizeof(pbcl_sec_t))
			return PBCL_ERR_SECTION_BOUNDS;

		const pbcl_sec_t *sec = (const pbcl_sec_t *)section_ptr;
		section_ptr += sizeof(pbcl_sec_t);

		if ((size_t)(section_end - section_ptr) < sec->tlv_len)
			return PBCL_ERR_SECTION_BOUNDS;

		size_t tlv_remaining = sec->tlv_len;
		const uint8_t *tlv_ptr = section_ptr;
		while (tlv_remaining > 0) {
			if (tlv_remaining < sizeof(pbcl_tlv_t))
				return PBCL_ERR_TLV_BOUNDS;
			const pbcl_tlv_t *tlv = (const pbcl_tlv_t *)tlv_ptr;
			size_t tlv_size = sizeof(pbcl_tlv_t) + tlv->len;
			if (tlv_remaining < tlv_size)
				return PBCL_ERR_TLV_BOUNDS;
			tlv_ptr += tlv_size;
			tlv_remaining -= tlv_size;
		}

		section_ptr += sec->tlv_len;
		sections_seen++;
	}

	if (section_ptr != section_end)
		return PBCL_ERR_SECTION_BOUNDS;

	if (sections_seen != hdr->sections)
		return PBCL_ERR_SECTION_COUNT;

	out->data = data;
	out->length = len;
	out->header = hdr;
	out->section_begin = data + hdr->hdr_size;
	out->section_end = section_end;
	out->section_count = sections_seen;
	return PBCL_OK;
}

static inline const pbcl_hdr_t *pbcl_doc_header(const pbcl_doc_t *doc) {
	return doc ? doc->header : NULL;
}

static inline uint16_t pbcl_doc_section_count(const pbcl_doc_t *doc) {
	return doc ? doc->section_count : 0;
}

static inline const pbcl_sec_t *pbcl_doc_first_section(const pbcl_doc_t *doc) {
	if (!doc || doc->section_count == 0)
		return NULL;
	return (const pbcl_sec_t *)doc->section_begin;
}

static inline const pbcl_sec_t *
pbcl_doc_next_section(const pbcl_doc_t *doc, const pbcl_sec_t *current) {
	if (!doc || !current)
		return NULL;

	const uint8_t *next =
	    (const uint8_t *)current + sizeof(pbcl_sec_t) + current->tlv_len;
	if (next >= doc->section_end)
		return NULL;

	if ((size_t)(doc->section_end - next) < sizeof(pbcl_sec_t))
		return NULL;

	return (const pbcl_sec_t *)next;
}

static inline const uint8_t *pbcl_section_payload(const pbcl_doc_t *doc,
                                                  const pbcl_sec_t *sec,
                                                  size_t *len_out) {
	(void)doc;
	if (!sec)
		return NULL;
	if (len_out)
		*len_out = sec->tlv_len;
	return (const uint8_t *)sec + sizeof(pbcl_sec_t);
}

static inline pbcl_tlv_iter_t pbcl_tlv_iter_init(const pbcl_doc_t *doc,
                                                 const pbcl_sec_t *sec) {
	(void)doc;
	pbcl_tlv_iter_t iter = {0};
	if (!sec)
		return iter;
	iter.cursor = (const uint8_t *)sec + sizeof(pbcl_sec_t);
	iter.end = iter.cursor + sec->tlv_len;
	return iter;
}

static inline bool pbcl_tlv_next(pbcl_tlv_iter_t *iter, pbcl_tlv_view_t *view) {
	if (!iter || !view)
		return false;
	if (!iter->cursor || iter->cursor >= iter->end)
		return false;
	size_t remaining = (size_t)(iter->end - iter->cursor);
	if (remaining < sizeof(pbcl_tlv_t)) {
		iter->cursor = iter->end;
		return false;
	}
	const pbcl_tlv_t *tlv = (const pbcl_tlv_t *)iter->cursor;
	size_t total = sizeof(pbcl_tlv_t) + tlv->len;
	if (remaining < total) {
		iter->cursor = iter->end;
		return false;
	}
	view->tlv = tlv;
	view->value = iter->cursor + sizeof(pbcl_tlv_t);
	iter->cursor += total;
	return true;
}

#endif
