#ifndef __MOTOR_H__
#define __MOTOR_H__

#include <stddef.h>
#include <stdint.h>

int motor_system_init(void);
void motor_system_reset(void);
int motor_apply_pbcl_blob(const uint8_t *blob, size_t len);

uint32_t motor_servo_count(void);

#endif // __MOTOR_H__
