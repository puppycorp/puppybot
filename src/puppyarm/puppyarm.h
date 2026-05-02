#ifndef PUPPYARM_H
#define PUPPYARM_H

#include <stdbool.h>
#include <stdint.h>

#include "puppyarm/puppyarm_controller.h"
#include "puppyarm/puppyarm_kinematics.h"
#include "puppyarm/puppyarm_profile.h"

int puppyarm_init_default(uint8_t uart_port, int tx_pin, int rx_pin,
                          uint32_t baud_rate, uint32_t now_ms);
int puppyarm_start(uint32_t now_ms);
int puppyarm_step(uint32_t now_ms);
void puppyarm_stop(uint32_t now_ms);
int puppyarm_set_speed(uint16_t speed);
int puppyarm_stop_joint(uint8_t joint, uint32_t now_ms);
void puppyarm_clear_faults(void);
int puppyarm_clear_joint_fault(uint8_t joint);
int puppyarm_goto_ticks(const int32_t ticks[PUPPYARM_JOINT_COUNT],
                        uint16_t speed, uint32_t now_ms);
int puppyarm_goto_angles(const float angles_rad[PUPPYARM_JOINT_COUNT],
                         uint16_t speed, uint32_t now_ms);
int puppyarm_goto_coords(float x_mm, float y_mm, float z_mm, uint16_t speed,
                         uint32_t now_ms);
int puppyarm_jog(uint8_t joint, int8_t direction, uint16_t speed,
                 uint32_t now_ms);
int puppyarm_hold(uint16_t speed, uint32_t now_ms);
int puppyarm_set_joint_tick(uint8_t joint, int32_t tick, uint16_t speed,
                            uint32_t now_ms);
int puppyarm_set_tick_limits(uint8_t joint, int32_t min_tick,
                             int32_t max_tick);
int puppyarm_set_tick_limits_enabled(uint8_t joint, bool enabled);
int puppyarm_move_relative(float dx_mm, float dy_mm, uint16_t speed,
                           uint32_t now_ms);
const puppyarm_controller_t *puppyarm_controller(void);

#endif
