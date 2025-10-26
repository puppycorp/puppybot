#include "command.h"
#include "command_handler.h"
#include "esp_log.h"
#include "esp_websocket_client.h"
#include "motor.h"

#define TAG "COMMAND"

void init_command_handler() { command_handler_init(); }

void handle_command(CommandPacket *cmd, esp_websocket_client_handle_t client) {
	if (!cmd)
		return;
	if (cmd->cmd_type == CMD_APPLY_CONFIG) {
		if (!cmd->cmd.apply_config.data || cmd->cmd.apply_config.length == 0) {
			ESP_LOGW(TAG, "Received empty PBCL config payload");
			return;
		}
		int rc = motor_apply_pbcl_blob(cmd->cmd.apply_config.data,
		                               cmd->cmd.apply_config.length);
		if (rc != 0) {
			ESP_LOGE(TAG, "motor_apply_pbcl_blob failed (%d)", rc);
		} else {
			ESP_LOGI(TAG, "Motor configuration applied (%u bytes)",
			         (unsigned)cmd->cmd.apply_config.length);
			command_handler_reload_motor_config();
		}
		return;
	}
	command_handler_handle(cmd, (void *)client);
}
