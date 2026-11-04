# Sourced by native build scripts after they set project_dir.
if [[ -z "${FLEXSCRIPT_COMPILER:-}" ]]; then
    bootstrap="$(command -v flexscript || true)"
    if [[ -z "$bootstrap" ]]; then bootstrap="$project_dir/../flexscript/build/flex"; fi
    python3 "$project_dir/src/scripts/prepare-native.py" \
        --source "${FLEXSCRIPT_SOURCE:-$project_dir/../flexscript}" --bootstrap "$bootstrap"
    export FLEXSCRIPT_COMPILER="$project_dir/build/native-toolchain/compiler-native"
    export FLEXSCRIPT_SOURCE="$project_dir/build/native-toolchain"
    export FLEXSCRIPT_ROOT="$FLEXSCRIPT_SOURCE"
    export FLEXSCRIPT_LIB="$FLEXSCRIPT_SOURCE/libs"
else
    export FLEXSCRIPT_SOURCE="${FLEXSCRIPT_SOURCE:-${FLEXSCRIPT_ROOT:-$project_dir/../flexscript}}"
    export FLEXSCRIPT_ROOT="${FLEXSCRIPT_ROOT:-$FLEXSCRIPT_SOURCE}"
    export FLEXSCRIPT_LIB="${FLEXSCRIPT_LIB:-$FLEXSCRIPT_ROOT/libs}"
fi
compiler="$FLEXSCRIPT_COMPILER"
