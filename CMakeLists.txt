cmake_minimum_required(VERSION 3.10)

project(puppybot C)

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
