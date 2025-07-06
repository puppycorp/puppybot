#ifndef WS_H
#define WS_H

#include "esp_event.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "esp_http_server.h"
#include "motor.h"
#include "command.h"
 
void websocket_app_start();
bool is_websocket_connected(void);
void websocket_send_status(void);

#endif // WS_H