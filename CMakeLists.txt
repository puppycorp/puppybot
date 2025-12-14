cmake_minimum_required(VERSION 3.10)

project(puppybot C)

set(PUPPYBOT_BUILD_VERSION "unknown")
set(PUPPYBOT_BUILD_NAME "puppybot")
set(VERSION_SCRIPT_PATH "${CMAKE_SOURCE_DIR}/scripts/build_version.sh")
if(EXISTS "${VERSION_SCRIPT_PATH}")
	execute_process(
		COMMAND "${VERSION_SCRIPT_PATH}" version
		WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
		RESULT_VARIABLE VERSION_SCRIPT_RESULT
		OUTPUT_VARIABLE VERSION_SCRIPT_OUTPUT
		OUTPUT_STRIP_TRAILING_WHITESPACE
	)
	if(VERSION_SCRIPT_RESULT EQUAL 0 AND VERSION_SCRIPT_OUTPUT)
		set(PUPPYBOT_BUILD_VERSION "${VERSION_SCRIPT_OUTPUT}")
	else()
		message(WARNING "Could not determine build version; falling back to \"${PUPPYBOT_BUILD_VERSION}\"")
	endif()

	execute_process(
		COMMAND "${VERSION_SCRIPT_PATH}" name
		WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
		RESULT_VARIABLE NAME_SCRIPT_RESULT
		OUTPUT_VARIABLE NAME_SCRIPT_OUTPUT
		OUTPUT_STRIP_TRAILING_WHITESPACE
	)
	if(NAME_SCRIPT_RESULT EQUAL 0 AND NAME_SCRIPT_OUTPUT)
		set(PUPPYBOT_BUILD_NAME "${NAME_SCRIPT_OUTPUT}")
	else()
		message(WARNING "Could not determine build name; falling back to \"${PUPPYBOT_BUILD_NAME}\"")
	endif()
else()
	message(WARNING "Version helper script not found at ${VERSION_SCRIPT_PATH}; using defaults")
endif()
message(STATUS "Build version: ${PUPPYBOT_BUILD_VERSION} (name: ${PUPPYBOT_BUILD_NAME})")

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED True)

# Automatically collect all app sources
file(GLOB_RECURSE APP_SOURCES "src/app/*.c")
file(GLOB HW_HOST_SOURCES "src/hw/host/*.c")

# Exclude sources that aren’t part of the runtime library
list(FILTER APP_SOURCES EXCLUDE REGEX ".*/test_main\\.c$")
list(FILTER APP_SOURCES EXCLUDE REGEX ".*/.*_tests\\.c$")

set(ALL_SOURCES ${APP_SOURCES} ${HW_HOST_SOURCES})

add_executable(puppybot
	main.c
	${ALL_SOURCES}
)

target_include_directories(puppybot PRIVATE src)

find_package(Threads REQUIRED)
target_link_libraries(puppybot PRIVATE Threads::Threads)

string(CONCAT VERSION_DEFINITION "\"${PUPPYBOT_BUILD_VERSION}\"")
target_compile_definitions(
	puppybot
	PRIVATE
		PUPPYBOT_BUILD_VERSION=${VERSION_DEFINITION}
)
string(CONCAT NAME_DEFINITION "\"${PUPPYBOT_BUILD_NAME}\"")
target_compile_definitions(
	puppybot
	PRIVATE
		PUPPYBOT_BUILD_NAME=${NAME_DEFINITION}
)
