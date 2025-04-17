# File: esp32/main/CMakeLists.txt

idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES
        bt
        nvs_flash
        esp_event
        esp_netif
        esp_wifi
        esp_timer
        esp_websocket_client
        app_update
        driver
)

if(DEFINED ENV{WIFI_SSID})
	message("Using WIFI_SSID: $ENV{WIFI_SSID}")
	target_compile_definitions(${COMPONENT_LIB} PRIVATE WIFI_SSID="$ENV{WIFI_SSID}")
endif()

if(DEFINED ENV{WIFI_PASS})
	message("Using WIFI_PASS: $ENV{WIFI_PASS}")
	target_compile_definitions(${COMPONENT_LIB} PRIVATE WIFI_PASS="$ENV{WIFI_PASS}")
endif()

if(DEFINED ENV{WIFI_AP_SSID})
	message("Using WIFI_AP_SSID: $ENV{WIFI_AP_SSID}")
	target_compile_definitions(${COMPONENT_LIB} PRIVATE WIFI_AP_SSID="$ENV{WIFI_AP_SSID}")
endif()

if(DEFINED ENV{WIFI_AP_PASS})
	message("Using WIFI_AP_PASS: $ENV{WIFI_AP_PASS}")
	target_compile_definitions(${COMPONENT_LIB} PRIVATE WIFI_AP_PASS="$ENV{WIFI_AP_PASS}")
endif()

if(DEFINED ENV{SERVER_HOST})
	message("Using SERVER_HOST: $ENV{SERVER_HOST}")
	target_compile_definitions(${COMPONENT_LIB} PRIVATE SERVER_HOST="$ENV{SERVER_HOST}")
endif()