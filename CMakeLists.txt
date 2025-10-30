cmake_minimum_required(VERSION 3.10)

project(puppybot C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED True)

# Automatically collect all .c files from src directory
file(GLOB SRC_SOURCES "src/*.c")

# Exclude unit test sources from the desktop build
list(FILTER SRC_SOURCES EXCLUDE REGEX ".*/test_main\\.c$")
list(FILTER SRC_SOURCES EXCLUDE REGEX ".*/.*_tests\\.c$")

add_executable(puppybot
	main.c
	${SRC_SOURCES}
)

target_include_directories(puppybot PRIVATE src)

find_package(Threads REQUIRED)
target_link_libraries(puppybot PRIVATE Threads::Threads)
