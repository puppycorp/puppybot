#ifndef PUPPYARM_H
#define PUPPYARM_H

#include <stdint.h>

#include "puppyarm/puppyarm_controller.h"
#include "puppyarm/puppyarm_kinematics.h"
#include "puppyarm/puppyarm_profile.h"

int puppyarm_init_default(uint8_t uart_port, int tx_pin, int rx_pin,
                          uint32_t baud_rate, uint32_t now_ms);
int puppyarm_start(uint32_t now_ms);
int puppyarm_step(uint32_t now_ms);
void puppyarm_stop(uint32_t now_ms);
int puppyarm_goto_ticks(const int32_t ticks[PUPPYARM_JOINT_COUNT],
                        uint16_t speed, uint32_t now_ms);
int puppyarm_goto_angles(const float angles_rad[PUPPYARM_JOINT_COUNT],
                         uint16_t speed, uint32_t now_ms);
int puppyarm_goto_coords(float x_mm, float y_mm, float z_mm, uint16_t speed,
                         uint32_t now_ms);
int puppyarm_jog(uint8_t joint, int8_t direction, uint16_t speed,
                 uint32_t now_ms);
const puppyarm_controller_t *puppyarm_controller(void);

#endif
