find . -type f \( -name '*.c' -o -name '*.h' \) -exec clang-format -i {} +
npm run format