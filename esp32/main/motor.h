#ifndef __MOTOR_H__
#define __MOTOR_H__

#include <stddef.h>
#include <stdint.h>

int motor_system_init(void);
void motor_system_reset(void);
int motor_apply_pbcl_blob(const uint8_t *blob, size_t len);

void servo_set_angle(uint8_t servo_id, uint32_t angle);
uint32_t motor_servo_count(void);
uint32_t motor_servo_boot_angle(uint8_t servo_id);

#endif // __MOTOR_H__
