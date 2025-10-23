#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build/tests"
mkdir -p "$BUILD_DIR"

: "${CC:=gcc}"
: "${CFLAGS:=}"

"$CC" -std=c11 -Wall -Wextra -Werror -Isrc $CFLAGS \
  "$ROOT_DIR/src/test_main.c" -o "$BUILD_DIR/test_runner" -lm

"$BUILD_DIR/test_runner" "$@"
