#ifndef COMMAND_H
#define COMMAND_H

#include "esp_websocket_client.h"

#include "../../src/protocol.h"

void handle_command(CommandPacket *cmd, esp_websocket_client_handle_t *client);
void init_command_handler();

#endif // COMMAND_H