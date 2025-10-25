#pragma once

#include <stdint.h>

#include "motor_runtime.h"

void motor_slots_reset(void);
void motor_slots_register(motor_rt_t *motor);

motor_rt_t *motor_slots_drive(int idx);
int motor_slots_drive_count(void);

motor_rt_t *motor_slots_servo(int idx);
int motor_slots_servo_count(void);
float motor_slots_servo_boot_angle(int idx);
