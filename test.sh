#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build/tests"
mkdir -p "$BUILD_DIR"

: "${CC:=gcc}"
: "${CFLAGS:=}"

"$CC" -std=c11 -Wall -Wextra -Werror -DUNIT_TEST -Isrc -Iesp32/main $CFLAGS \
  "$ROOT_DIR/src/test_main.c" \
  "$ROOT_DIR/src/motor_runtime_tests.c" \
  "$ROOT_DIR/src/app_tests.c" \
  "$ROOT_DIR/src/pbcl_tests.c" \
  "$ROOT_DIR/src/motor_runtime.c" \
  "$ROOT_DIR/src/pbcl_motor_handler.c" \
  "$ROOT_DIR/src/main.c" \
  -o "$BUILD_DIR/test_runner" -lm

"$BUILD_DIR/test_runner" "$@"
