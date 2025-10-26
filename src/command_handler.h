#ifndef COMMAND_HANDLER_H
#define COMMAND_HANDLER_H

#include "protocol.h"
#include <stdbool.h>
#include <stdint.h>

// Initialize the command handler
void command_handler_init(void);

// Handle a command packet (can be called from websocket/bluetooth handlers)
void command_handler_handle(CommandPacket *cmd, void *client);

// Re-synchronise internal servo timeout state after a new motor config loads.
void command_handler_reload_motor_config(void);

#endif // COMMAND_HANDLER_H
