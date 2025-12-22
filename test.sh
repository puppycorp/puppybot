#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build/tests"
mkdir -p "$BUILD_DIR"

: "${CC:=gcc}"
: "${CFLAGS:=}"

TEST_SOURCES=()
while IFS= read -r file; do
  TEST_SOURCES+=("$file")
done < <(find "$ROOT_DIR/src/tests" -maxdepth 1 -type f -name '*.c' ! -name 'test_main.c' | sort)

"$CC" -std=c11 -Wall -Wextra -Werror -DUNIT_TEST -Isrc -Iesp32/main $CFLAGS \
  "$ROOT_DIR/src/tests/test_main.c" \
  "${TEST_SOURCES[@]}" \
  "$ROOT_DIR/src/app/motor_config.c" \
  "$ROOT_DIR/src/app/motor_runtime.c" \
  "$ROOT_DIR/src/app/pbcl_motor_handler.c" \
  "$ROOT_DIR/src/app/main.c" \
  -o "$BUILD_DIR/test_runner" -lm

"$BUILD_DIR/test_runner" "$@"
