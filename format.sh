#!/usr/bin/env bash

if command -v clang-format >/dev/null 2>&1; then
  echo "Formatting C/C++ files in src/ (including hw/) and esp32/..."
  format_dirs=(src esp32/main)
  if [ -d esp32/components ]; then
    format_dirs+=(esp32/components)
  fi
  find "${format_dirs[@]}" -type f \( -name '*.c' -o -name '*.h' \) -exec clang-format -i {} +
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
