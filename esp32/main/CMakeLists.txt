idf_component_register(SRCS "main.c"
                    INCLUDE_DIRS ".")

if(DEFINED ENV{WIFI_SSID})
	message("Using WIFI_SSID: $ENV{WIFI_SSID}")
	target_compile_definitions(${COMPONENT_LIB} PRIVATE WIFI_SSID="$ENV{WIFI_SSID}")
endif()

if(DEFINED ENV{WIFI_PASS})
	message("Using WIFI_PASS: $ENV{WIFI_PASS}")
	target_compile_definitions(${COMPONENT_LIB} PRIVATE WIFI_PASS="$ENV{WIFI_PASS}")
endif()

if(DEFINED ENV{SERVER_HOST})
	message("Using SERVER_HOST: $ENV{SERVER_HOST}")
	target_compile_definitions(${COMPONENT_LIB} PRIVATE SERVER_HOST="$ENV{SERVER_HOST}")
endif()