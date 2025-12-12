# File: esp32/main/CMakeLists.txt

#
# Include all ESP32-specific sources from the hw tree
#
file(GLOB ESP32_HW_SRCS "../../src/hw/esp32/*.c")
set(COMPONENT_SRCS ${ESP32_HW_SRCS})

# Bring in the shared app sources
file(GLOB_RECURSE APP_COMMON_SRCS "../../src/app/*.c")
list(APPEND COMPONENT_SRCS ${APP_COMMON_SRCS})

set(DRIVER_COMPONENTS driver)
idf_build_get_property(idf_path IDF_PATH)
if(idf_path)
        if(EXISTS "${idf_path}/components/esp_driver_gpio")
                list(APPEND DRIVER_COMPONENTS esp_driver_gpio)
        endif()
        if(EXISTS "${idf_path}/components/esp_driver_ledc")
                list(APPEND DRIVER_COMPONENTS esp_driver_ledc)
        endif()
        if(EXISTS "${idf_path}/components/esp_driver_uart")
                list(APPEND DRIVER_COMPONENTS esp_driver_uart)
        endif()
endif()

idf_component_register(
    SRCS ${COMPONENT_SRCS}
    INCLUDE_DIRS "." "../../src" "../../src/hw/esp32"
    REQUIRES
        bt
        nvs_flash
        esp_event
        esp_netif
        esp_wifi
        esp_timer
        esp_http_server
        esp_websocket_client
        app_update
        ${DRIVER_COMPONENTS}
)

if(DEFINED ENV{WIFI_CREDENTIALS})
        set(WIFI_CREDENTIALS_VALUE "$ENV{WIFI_CREDENTIALS}")
        string(REPLACE "\\" "\\\\" WIFI_CREDENTIALS_VALUE "${WIFI_CREDENTIALS_VALUE}")
        string(REPLACE "\"" "\\\"" WIFI_CREDENTIALS_VALUE "${WIFI_CREDENTIALS_VALUE}")
        string(REPLACE ";" "\\;" WIFI_CREDENTIALS_VALUE "${WIFI_CREDENTIALS_VALUE}")
        message("Using WIFI_CREDENTIALS: ${WIFI_CREDENTIALS_VALUE}")
        target_compile_definitions(${COMPONENT_LIB} PRIVATE WIFI_CREDENTIALS="${WIFI_CREDENTIALS_VALUE}")
endif()

if(DEFINED ENV{PUPPY_VARIANT})
        string(TOUPPER "$ENV{PUPPY_VARIANT}" PUPPY_VARIANT_RAW)
        string(REGEX REPLACE "[^A-Z0-9]" "" PUPPY_VARIANT_TOKEN ${PUPPY_VARIANT_RAW})
        if(PUPPY_VARIANT_TOKEN STREQUAL "")
                set(PUPPY_VARIANT_TOKEN "PUPPYBOT")
        endif()
        message("Using PUPPY_VARIANT: ${PUPPY_VARIANT_TOKEN}")
        target_compile_definitions(${COMPONENT_LIB} PRIVATE PUPPY_VARIANT_${PUPPY_VARIANT_TOKEN})
else()
        message("Using default PUPPY_VARIANT: PUPPYBOT")
        target_compile_definitions(${COMPONENT_LIB} PRIVATE PUPPY_VARIANT_PUPPYBOT)
endif()

if(DEFINED ENV{SERVER_HOST})
        set(SERVER_HOST_VALUE "$ENV{SERVER_HOST}")
        string(REPLACE "\\" "\\\\" SERVER_HOST_VALUE "${SERVER_HOST_VALUE}")
        string(REPLACE "\"" "\\\"" SERVER_HOST_VALUE "${SERVER_HOST_VALUE}")
        message("Using SERVER_HOST: ${SERVER_HOST_VALUE}")
        target_compile_definitions(${COMPONENT_LIB} PRIVATE SERVER_HOST="${SERVER_HOST_VALUE}")
endif()

if(DEFINED ENV{DEVICE_ID})
        set(DEVICE_ID_VALUE "$ENV{DEVICE_ID}")
        string(REPLACE "\\" "\\\\" DEVICE_ID_VALUE "${DEVICE_ID_VALUE}")
        string(REPLACE "\"" "\\\"" DEVICE_ID_VALUE "${DEVICE_ID_VALUE}")
        message("Using DEVICE_ID: ${DEVICE_ID_VALUE}")
        target_compile_definitions(${COMPONENT_LIB} PRIVATE DEVICE_ID="${DEVICE_ID_VALUE}")
endif()
