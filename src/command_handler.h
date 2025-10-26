#ifndef COMMAND_HANDLER_H
#define COMMAND_HANDLER_H

#include "protocol.h"
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Forward declarations for opaque timer handle
typedef void *CommandTimerHandle;

// Operations structure for platform-specific implementations
typedef struct CommandOps {
	// Timer operations
	CommandTimerHandle (*timer_create)(void (*callback)(void *), void *arg,
	                                   const char *name);
	int (*timer_start_once)(CommandTimerHandle timer, uint64_t timeout_us);
	int (*timer_stop)(CommandTimerHandle timer);

	// Logging operations
	void (*log_info)(const char *tag, const char *format, ...);
	void (*log_warning)(const char *tag, const char *format, ...);
	void (*log_error)(const char *tag, const char *format, ...);

	// Motor control operations
	void (*motor_a_forward)(uint8_t speed);
	void (*motor_a_backward)(uint8_t speed);
	void (*motor_a_stop)(void);
	void (*motor_b_forward)(uint8_t speed);
	void (*motor_b_backward)(uint8_t speed);
	void (*motor_b_stop)(void);

	// Servo control operations
	void (*servo_set_angle)(uint8_t servo_id, uint32_t angle);
	uint32_t (*servo_count)(void);
	uint32_t (*servo_boot_angle)(uint8_t servo_id);

	// WebSocket communication
	int (*websocket_send_pong)(void *client);
} CommandOps;

// Initialize the command handler with platform-specific operations
void command_handler_init(const CommandOps *ops);

// Handle a command packet (can be called from websocket/bluetooth handlers)
void command_handler_handle(CommandPacket *cmd, void *client);

// Re-synchronise internal servo timeout state after a new motor config loads.
void command_handler_reload_motor_config(void);

#ifdef __cplusplus
}
#endif

#endif // COMMAND_HANDLER_H
