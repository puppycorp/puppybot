#include "bluetooth.h"

#include "command.h"
#include "esp_log.h"
#include "sdkconfig.h"

#include <stdbool.h>

#define BLUETOOTH_TAG "BLE_CTRL"

#if CONFIG_BT_BLUEDROID_ENABLED

#include "esp_bt.h"
#include "esp_bt_defs.h"
#include "esp_bt_main.h"
#include "esp_gap_ble_api.h"
#include "esp_gatt_common_api.h"
#include "esp_gatts_api.h"
#define GATTS_SERVICE_UUID 0x00FF
#define GATTS_CHAR_UUID 0xFF01
#define GATTS_NUM_HANDLE 4
#define DEVICE_NAME "PUPPYBOT"
#define ESP_APP_ID 0x55

static const uint16_t service_uuid = GATTS_SERVICE_UUID;
static const uint16_t char_uuid = GATTS_CHAR_UUID;
static const uint8_t service_uuid128[ESP_UUID_LEN_128] = {
    0xfb, 0x34, 0x9b, 0x5f, 0x80, 0x00, 0x00, 0x80,
    0x00, 0x10, 0x00, 0x00, 0xff, 0x00, 0x00, 0x00,
};

static uint16_t gatts_service_handle = 0;
static uint16_t char_handle = 0;
static uint16_t ccc_handle = 0;
static uint16_t ccc_val = 0x0000; // 2-byte CCCD value
static bool bluetooth_started = false;

static esp_ble_adv_data_t adv_data = {
    .set_scan_rsp = false,
    .include_name = true,
    .include_txpower = true,
    .min_interval = 0x20,
    .max_interval = 0x40,
    .appearance = 0x00,
    .service_uuid_len = sizeof(service_uuid128),
    .p_service_uuid = (uint8_t *)service_uuid128,
    .flag = (ESP_BLE_ADV_FLAG_GEN_DISC | ESP_BLE_ADV_FLAG_BREDR_NOT_SPT),
};

static esp_ble_adv_params_t adv_params = {
    .adv_int_min = 0x20,
    .adv_int_max = 0x40,
    .adv_type = ADV_TYPE_IND,
    .own_addr_type = BLE_ADDR_TYPE_PUBLIC,
    .channel_map = ADV_CHNL_ALL,
    .adv_filter_policy = ADV_FILTER_ALLOW_SCAN_ANY_CON_ANY,
};

static const uint16_t primary_service_uuid = ESP_GATT_UUID_PRI_SERVICE;
static const uint16_t char_decl_uuid = ESP_GATT_UUID_CHAR_DECLARE;
static const uint16_t char_client_config_uuid =
    ESP_GATT_UUID_CHAR_CLIENT_CONFIG;

static const esp_gatts_attr_db_t gatt_db[GATTS_NUM_HANDLE] = {
    // Service Declaration
    [0] = {{ESP_GATT_AUTO_RSP},
           {ESP_UUID_LEN_16, (uint8_t *)&primary_service_uuid,
            ESP_GATT_PERM_READ, sizeof(uint16_t), sizeof(service_uuid),
            (uint8_t *)&service_uuid}},
    // Characteristic Declaration (WRITE)
    [1] = {{ESP_GATT_AUTO_RSP},
           {ESP_UUID_LEN_16, (uint8_t *)&char_decl_uuid, ESP_GATT_PERM_READ,
            sizeof(uint8_t), sizeof(uint8_t),
            (uint8_t *)&(uint8_t){ESP_GATT_CHAR_PROP_BIT_WRITE}}},
    // Characteristic Value
    [2] = {{ESP_GATT_AUTO_RSP},
           {ESP_UUID_LEN_16, (uint8_t *)&char_uuid, ESP_GATT_PERM_WRITE, 512, 0,
            NULL}},
    // Client Characteristic Configuration Descriptor
    [3] = {{ESP_GATT_AUTO_RSP},
           {ESP_UUID_LEN_16, (uint8_t *)&char_client_config_uuid,
            ESP_GATT_PERM_READ | ESP_GATT_PERM_WRITE, sizeof(uint16_t),
            sizeof(uint16_t), (uint8_t *)&ccc_val}},
};

static void gap_event_handler(esp_gap_ble_cb_event_t event,
                              esp_ble_gap_cb_param_t *param) {
    ESP_LOGD(BLUETOOTH_TAG, "gap_event_handler called: event=0x%02x", event);
    switch (event) {
    case ESP_GAP_BLE_ADV_DATA_SET_COMPLETE_EVT:
        ESP_LOGD(BLUETOOTH_TAG, "ADV data ready, starting advertising");
        esp_ble_gap_start_advertising(&adv_params);
        break;
    case ESP_GAP_BLE_ADV_START_COMPLETE_EVT:
        ESP_LOGD(BLUETOOTH_TAG, "Advertising started, status=%d",
                 param->adv_start_cmpl.status);
        break;
    default:
        break;
    }
}

static void handle_control_payload(const uint8_t *data, uint16_t len) {
    if (len < 4) {
        ESP_LOGW(BLUETOOTH_TAG, "Ignoring short payload len=%u", len);
        return;
    }

    uint16_t payload_len = (uint16_t)(data[2] | (data[3] << 8));
    if ((uint16_t)(payload_len + 4) > len) {
        ESP_LOGW(BLUETOOTH_TAG,
                 "Payload length mismatch header=%u actual=%u", payload_len,
                 len);
        return;
    }

    CommandPacket pkt = {0};
    parse_cmd((uint8_t *)data, &pkt);
    handle_command(&pkt, NULL);
}

static void gatts_event_handler(esp_gatts_cb_event_t event,
                                esp_gatt_if_t gatts_if,
                                esp_ble_gatts_cb_param_t *param) {
    ESP_LOGD(BLUETOOTH_TAG, "gatts_event_handler called: event=%d, gatts_if=%d",
             event, gatts_if);
    switch (event) {
    case ESP_GATTS_REG_EVT:
        ESP_LOGD(BLUETOOTH_TAG, "ESP_GATTS_REG_EVT");
        esp_ble_gap_set_device_name(DEVICE_NAME);
        esp_ble_gap_config_adv_data(&adv_data);
        esp_ble_gatts_create_attr_tab(gatt_db, gatts_if, GATTS_NUM_HANDLE, 0);
        break;
    case ESP_GATTS_CREAT_ATTR_TAB_EVT:
        ESP_LOGD(BLUETOOTH_TAG, "ESP_GATTS_CREAT_ATTR_TAB_EVT: status=%d",
                 param->add_attr_tab.status);
        if (param->add_attr_tab.status == ESP_GATT_OK) {
            gatts_service_handle = param->add_attr_tab.handles[0];
            char_handle = param->add_attr_tab.handles[2];
            ccc_handle = param->add_attr_tab.handles[3];
            esp_ble_gatts_start_service(gatts_service_handle);
        } else {
            ESP_LOGE(BLUETOOTH_TAG,
                     "Failed to create attribute table: status=0x%02x",
                     param->add_attr_tab.status);
        }
        break;
    case ESP_GATTS_WRITE_EVT:
        ESP_LOGD(BLUETOOTH_TAG, "ESP_GATTS_WRITE_EVT: handle=0x%04x, len=%d",
                 param->write.handle, param->write.len);
        if (param->write.is_prep) {
            break;
        }
        if (param->write.handle == char_handle) {
            handle_control_payload(param->write.value, param->write.len);
        } else if (param->write.handle == ccc_handle &&
                   param->write.len == sizeof(uint16_t)) {
            ccc_val = param->write.value[0] | (param->write.value[1] << 8);
            ESP_LOGD(BLUETOOTH_TAG, "Updated CCC value=0x%04x", ccc_val);
        }
        break;
    case ESP_GATTS_CONNECT_EVT:
        ESP_LOGD(BLUETOOTH_TAG, "ESP_GATTS_CONNECT_EVT");
        break;
    case ESP_GATTS_DISCONNECT_EVT:
        ESP_LOGD(BLUETOOTH_TAG, "ESP_GATTS_DISCONNECT_EVT");
        esp_ble_gap_start_advertising(&adv_params);
        break;
    default:
        break;
    }
}

esp_err_t bluetooth_app_start(void) {
    if (bluetooth_started) {
        ESP_LOGI(BLUETOOTH_TAG, "Bluetooth already started");
        return ESP_OK;
    }

    esp_err_t ret = esp_bt_controller_mem_release(ESP_BT_MODE_CLASSIC_BT);
    if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(BLUETOOTH_TAG, "Failed to release classic BT memory: %s",
                 esp_err_to_name(ret));
        return ret;
    }

    esp_bt_controller_status_t status = esp_bt_controller_get_status();
    if (status == ESP_BT_CONTROLLER_STATUS_IDLE) {
        esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
        ret = esp_bt_controller_init(&bt_cfg);
        if (ret != ESP_OK) {
            ESP_LOGE(BLUETOOTH_TAG, "controller init failed: %s",
                     esp_err_to_name(ret));
            return ret;
        }
        status = esp_bt_controller_get_status();
    }

    if (status != ESP_BT_CONTROLLER_STATUS_ENABLED) {
        ret = esp_bt_controller_enable(ESP_BT_MODE_BLE);
        if (ret != ESP_OK) {
            ESP_LOGE(BLUETOOTH_TAG, "controller enable failed: %s",
                     esp_err_to_name(ret));
            return ret;
        }
        status = esp_bt_controller_get_status();
    }

    esp_bluedroid_status_t bluedroid_status = esp_bluedroid_get_status();
    if (bluedroid_status == ESP_BLUEDROID_STATUS_UNINITIALIZED) {
        ret = esp_bluedroid_init();
        if (ret != ESP_OK) {
            ESP_LOGE(BLUETOOTH_TAG, "bluedroid init failed: %s",
                     esp_err_to_name(ret));
            return ret;
        }
        bluedroid_status = esp_bluedroid_get_status();
    }

    if (bluedroid_status != ESP_BLUEDROID_STATUS_ENABLED) {
        ret = esp_bluedroid_enable();
        if (ret != ESP_OK) {
            ESP_LOGE(BLUETOOTH_TAG, "bluedroid enable failed: %s",
                     esp_err_to_name(ret));
            return ret;
        }
    }

    ret = esp_ble_gap_register_callback(gap_event_handler);
    if (ret != ESP_OK) {
        ESP_LOGE(BLUETOOTH_TAG, "gap register callback failed: %s",
                 esp_err_to_name(ret));
        return ret;
    }

    ret = esp_ble_gatts_register_callback(gatts_event_handler);
    if (ret != ESP_OK) {
        ESP_LOGE(BLUETOOTH_TAG, "gatts register callback failed: %s",
                 esp_err_to_name(ret));
        return ret;
    }

    ret = esp_ble_gatts_app_register(ESP_APP_ID);
    if (ret != ESP_OK) {
        ESP_LOGE(BLUETOOTH_TAG, "gatts app register failed: %s",
                 esp_err_to_name(ret));
        return ret;
    }

    bluetooth_started = true;
    ESP_LOGI(BLUETOOTH_TAG, "Bluetooth controller started");
    return ESP_OK;
}

#else

esp_err_t bluetooth_app_start(void) {
    ESP_LOGW(BLUETOOTH_TAG, "Bluetooth disabled in sdkconfig");
    return ESP_ERR_NOT_SUPPORTED;
}

#endif // CONFIG_BT_BLUEDROID_ENABLED
