if command -v clang-format >/dev/null 2>&1; then
  find . -type f \( -name '*.c' -o -name '*.h' \) -exec clang-format -i {} +
else
  echo "clang-format not found; skipping C formatting"
fi
npm run format
