#!/usr/bin/env bash

if command -v clang-format >/dev/null 2>&1; then
  echo "Formatting C/C++ files in src/ and esp32/..."
  find src esp32 -type f \( -name '*.c' -o -name '*.h' \) -exec clang-format -i {} +
  echo "C/C++ formatting complete"
else
  echo "clang-format not found; skipping C formatting"
fi

if command -v npm >/dev/null 2>&1; then
  echo "Formatting TypeScript/Kotlin files..."
  npm run format
else
  echo "npm not found; skipping npm format"
fi
