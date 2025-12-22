#ifndef MOTOR_CONFIG_H
#define MOTOR_CONFIG_H

#include <stddef.h>
#include <stdint.h>

// Initialize motor system (hardware, tick timer, default config)
// Returns 0 on success, non-zero on error
int motor_system_init(void);

// Shutdown motor system and cleanup resources
void motor_system_shutdown(void);

// Reset motor configuration (clear registry and slots)
void motor_config_reset(void);

// Apply motor configuration from PBCL blob
// Returns 0 on success, non-zero on error
int motor_config_apply_blob(const uint8_t *blob, size_t len);

// Apply the default built-in motor configuration
// Returns 0 on success, non-zero on error
int motor_config_apply_default(void);

// Get the number of configured servo motors
uint32_t motor_config_servo_count(void);

// Retrieve the active PBCL configuration blob.
// Returns 0 on success, non-zero if not available.
int motor_config_get_active_blob(const uint8_t **blob_out, size_t *len_out);

// Persist the active configuration blob to storage.
// Returns 0 on success, non-zero on error.
int motor_config_persist_active(void);

#endif // MOTOR_CONFIG_H
