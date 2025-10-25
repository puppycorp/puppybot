#pragma once

#include <stddef.h>
#include <stdint.h>

#include "motor_runtime.h"
#include "pbcl.h"

int pbcl_apply_motor_section(const pbcl_sec_t *sec, const uint8_t *tlvs,
                             size_t len);
