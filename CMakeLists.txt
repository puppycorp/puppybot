cmake_minimum_required(VERSION 3.10)

project(puppybot C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED True)

# Automatically collect all .c files from src directory
file(GLOB SOURCES "src/*.c")

# Add main.c and all src files to the executable
add_executable(puppybot main.c ${SOURCES})

# Include src directory for headers
target_include_directories(puppybot PRIVATE src)