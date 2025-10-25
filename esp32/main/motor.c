#include "motor.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "motor_runtime.h"
#include "motor_slots.h"
#include "pbcl.h"
#include "pbcl_motor_handler.h"

#define TAG "MOTOR"

// Built-in PBCL configuration matching the default server profile.
// Allows the firmware to control drive motors and four servos before
// a remote ApplyConfig command arrives.
static const uint8_t k_default_motor_blob[] = {
    0x4c, 0x43, 0x42, 0x50, 0x01, 0x00, 0x00, 0x00, 0x06, 0x00, 0x14, 0x00,
    0x15, 0x01, 0x00, 0x00, 0x56, 0x8e, 0x3c, 0x75, 0x01, 0x00, 0x03, 0x00,
    0x01, 0x00, 0x00, 0x00, 0x26, 0x00, 0x00, 0x00, 0x01, 0x00, 0x0a, 0x00,
    0x64, 0x72, 0x69, 0x76, 0x65, 0x5f, 0x6c, 0x65, 0x66, 0x74, 0x0a, 0x00,
    0x0c, 0x00, 0x21, 0x00, 0xe8, 0x03, 0xe8, 0x03, 0xd0, 0x07, 0x00, 0x00,
    0x00, 0x00, 0x0b, 0x00, 0x04, 0x00, 0x19, 0x1a, 0x00, 0x00, 0x01, 0x00,
    0x03, 0x00, 0x02, 0x00, 0x00, 0x00, 0x27, 0x00, 0x00, 0x00, 0x01, 0x00,
    0x0b, 0x00, 0x64, 0x72, 0x69, 0x76, 0x65, 0x5f, 0x72, 0x69, 0x67, 0x68,
    0x74, 0x0a, 0x00, 0x0c, 0x00, 0x20, 0x01, 0xe8, 0x03, 0xe8, 0x03, 0xd0,
    0x07, 0x00, 0x00, 0x00, 0x00, 0x0b, 0x00, 0x04, 0x00, 0x1b, 0x0e, 0x00,
    0x00, 0x01, 0x00, 0x01, 0x00, 0x64, 0x00, 0x00, 0x00, 0x1b, 0x00, 0x00,
    0x00, 0x01, 0x00, 0x07, 0x00, 0x73, 0x65, 0x72, 0x76, 0x6f, 0x5f, 0x30,
    0x0a, 0x00, 0x0c, 0x00, 0x0d, 0x02, 0x32, 0x00, 0xe8, 0x03, 0xd0, 0x07,
    0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x65, 0x00, 0x00, 0x00,
    0x1b, 0x00, 0x00, 0x00, 0x01, 0x00, 0x07, 0x00, 0x73, 0x65, 0x72, 0x76,
    0x6f, 0x5f, 0x31, 0x0a, 0x00, 0x0c, 0x00, 0x15, 0x03, 0x32, 0x00, 0xe8,
    0x03, 0xd0, 0x07, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x66,
    0x00, 0x00, 0x00, 0x1b, 0x00, 0x00, 0x00, 0x01, 0x00, 0x07, 0x00, 0x73,
    0x65, 0x72, 0x76, 0x6f, 0x5f, 0x32, 0x0a, 0x00, 0x0c, 0x00, 0x16, 0x04,
    0x32, 0x00, 0xe8, 0x03, 0xd0, 0x07, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00,
    0x01, 0x00, 0x67, 0x00, 0x00, 0x00, 0x1b, 0x00, 0x00, 0x00, 0x01, 0x00,
    0x07, 0x00, 0x73, 0x65, 0x72, 0x76, 0x6f, 0x5f, 0x33, 0x0a, 0x00, 0x0c,
    0x00, 0x17, 0x05, 0x32, 0x00, 0xe8, 0x03, 0xd0, 0x07, 0x00, 0x00, 0x00,
    0x00};

static TaskHandle_t g_motor_tick_task = NULL;

static void motor_tick_task(void *arg) {
	(void)arg;
	while (1) {
		uint32_t now = (uint32_t)(esp_timer_get_time() / 1000);
		motor_tick_all(now);
		vTaskDelay(pdMS_TO_TICKS(5));
	}
}

int motor_system_init(void) {
	motor_hw_init();
	if (g_motor_tick_task == NULL) {
		BaseType_t rc = xTaskCreate(motor_tick_task, "motor_tick", 2048, NULL,
		                            tskIDLE_PRIORITY + 1, &g_motor_tick_task);
		if (rc != pdPASS) {
			ESP_LOGE(TAG, "Failed to create motor tick task");
			g_motor_tick_task = NULL;
			return -1;
		}
	}
	if (motor_count() == 0) {
		int rc = motor_apply_pbcl_blob(k_default_motor_blob,
		                               sizeof(k_default_motor_blob));
		if (rc != 0) {
			ESP_LOGW(TAG, "Failed to load built-in motor config (%d)", rc);
		}
	}
	return 0;
}

void motor_system_reset(void) {
	motor_registry_clear();
	motor_slots_reset();
}

static int apply_sections(const pbcl_doc_t *doc) {
	const pbcl_sec_t *sec = pbcl_doc_first_section(doc);
	while (sec) {
		const uint8_t *payload = pbcl_section_payload(doc, sec, NULL);
		if (!payload)
			return -1;
		if (sec->class_id == PBCL_CLASS_MOTOR) {
			int rc = pbcl_apply_motor_section(sec, payload, sec->tlv_len);
			if (rc != 0)
				return rc;
		}
		sec = pbcl_doc_next_section(doc, sec);
	}
	return 0;
}

int motor_apply_pbcl_blob(const uint8_t *blob, size_t len) {
	if (!blob || len == 0)
		return -1;

	pbcl_doc_t doc;
	pbcl_status_t st = pbcl_parse(blob, len, &doc);
	if (st != PBCL_OK) {
		ESP_LOGE(TAG, "pbcl_parse failed (%d)", (int)st);
		return -2;
	}

	motor_system_reset();

	int rc = apply_sections(&doc);
	if (rc != 0)
		return rc;

	for (int i = 0; i < motor_slots_drive_count(); ++i) {
		motor_rt_t *m = motor_slots_drive(i);
		if (m)
			motor_stop(m->node_id);
	}

	int servo_count = motor_slots_servo_count();
	for (int i = 0; i < servo_count; ++i) {
		float boot = motor_slots_servo_boot_angle(i);
		motor_rt_t *m = motor_slots_servo(i);
		if (m)
			motor_set_angle(m->node_id, boot);
	}

	ESP_LOGI(TAG, "Loaded %d motors (%d drive, %d servo)", motor_count(),
	         motor_slots_drive_count(), motor_slots_servo_count());
	return 0;
}

static motor_rt_t *drive_motor(int idx) { return motor_slots_drive(idx); }

static float speed_to_unit(uint8_t duty) { return (float)duty / 255.0f; }

void motorA_forward(uint8_t speed) {
	motor_rt_t *m = drive_motor(0);
	if (!m)
		return;
	float s = speed_to_unit(speed);
	motor_set_speed(m->node_id, s);
}

void motorA_backward(uint8_t speed) {
	motor_rt_t *m = drive_motor(0);
	if (!m)
		return;
	float s = -speed_to_unit(speed);
	motor_set_speed(m->node_id, s);
}

void motorA_stop(void) {
	motor_rt_t *m = drive_motor(0);
	if (!m)
		return;
	motor_stop(m->node_id);
}

void motorB_forward(uint8_t speed) {
	motor_rt_t *m = drive_motor(1);
	if (!m)
		return;
	float s = speed_to_unit(speed);
	motor_set_speed(m->node_id, s);
}

void motorB_backward(uint8_t speed) {
	motor_rt_t *m = drive_motor(1);
	if (!m)
		return;
	float s = -speed_to_unit(speed);
	motor_set_speed(m->node_id, s);
}

void motorB_stop(void) {
	motor_rt_t *m = drive_motor(1);
	if (!m)
		return;
	motor_stop(m->node_id);
}

void servo_set_angle(uint8_t servo_id, uint32_t angle) {
	motor_rt_t *m = motor_slots_servo((int)servo_id);
	if (!m)
		return;
	motor_set_angle(m->node_id, (float)angle);
}

uint32_t motor_servo_count(void) { return (uint32_t)motor_slots_servo_count(); }

uint32_t motor_servo_boot_angle(uint8_t servo_id) {
	float boot = motor_slots_servo_boot_angle((int)servo_id);
	if (boot < 0)
		boot = 0;
	if (boot > 180)
		boot = 180;
	return (uint32_t)lroundf(boot);
}
