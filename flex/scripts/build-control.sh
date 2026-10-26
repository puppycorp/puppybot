#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_dir"
dependency="${FLEXSCRIPT_ROOT:-$project_dir/../flexscript}"
if [[ ! -f "$dependency/libs/ml/pup/gpu.flex" && -z "${FLEXSCRIPT_ROOT:-}" ]]; then
    dependency="$project_dir/build/flex/launch/gpu-inference-review"
fi
if [[ ! -f "$dependency/libs/ml/pup/gpu.flex" ]]; then
    echo 'Set FLEXSCRIPT_ROOT to a Flexscript source checkout with native Pup GPU support.' >&2
    exit 1
fi
dependency="$(cd "$dependency" && pwd)"
bootstrap="${FLEXSCRIPT_COMPILER:-$project_dir/build/flex/pup-compiler}"
if [[ ! -x "$bootstrap" ]]; then bootstrap="$(command -v flexscript || true)"; fi
if [[ ! -x "$bootstrap" ]]; then bootstrap="$project_dir/../flexscript/build/flex"; fi
if [[ ! -x "$bootstrap" ]]; then echo 'Set FLEXSCRIPT_COMPILER to a native Flexscript compiler.' >&2; exit 1; fi
if [[ ! -s build/flex/sim/puppybot.bin ]]; then
    echo 'The shared simulator model asset build/flex/sim/puppybot.bin is required.' >&2
    exit 1
fi

mkdir -p build/flex/control/kernels build/flex/control/compiler-source build/flex/sim
exec 9>build/flex/control/build.lock
flock 9
compile_native() {
    local input="$1" output="$2"
    "$compiler" "$input" -o "$output.tmp.$$"
    mv -f "$output.tmp.$$" "$output"
}
compile_kernel() {
    local input="$1" output="$2"
    "$compiler" --target ptx "$input" -o "$output.tmp.$$"
    mv -f "$output.tmp.$$" "$output"
}
stage="$project_dir/build/flex/control/compiler-source"
for directory in compiler vm lib; do
    mkdir -p "$stage/$directory"
    cp -a "$dependency/$directory/." "$stage/$directory/"
done
patch_file="$project_dir/flex/compiler/gpu-inference.patch"
if patch --batch --dry-run --forward -p1 -d "$stage" -i "$patch_file" >/dev/null 2>&1; then
    patch --batch --forward -p1 -d "$stage" -i "$patch_file" >/dev/null
elif ! patch --batch --dry-run --reverse -p1 -d "$stage" -i "$patch_file" >/dev/null 2>&1; then
    echo 'GPU compiler patch does not match the selected dependency.' >&2
    exit 1
fi
compiler="$project_dir/build/flex/control/compiler"
"$bootstrap" "$stage/compiler/main.flex" -o "$compiler.tmp"
mv -f "$compiler.tmp" "$compiler"

# Import adapters contain native Flexscript paths; no Python generators run.
printf 'import "%s/lib/device.flex";\n' "$dependency" > build/flex/pup-device.flex
printf 'import "%s/libs/ml/pup/parser.flex";\n' "$dependency" > build/flex/pup-parser.flex
printf 'import "%s/libs/ml/pup/gpu/kernels/ops-body.flex";\n' "$dependency" > build/flex/pup-kernel-ops.flex
printf 'import "%s/libs/ml/pup/gpu/kernels/pack.flex";\n' "$dependency" > build/flex/pup-kernel-pack.flex
compile_native flex/control/prepare.flex build/flex/control/prepare
build/flex/control/prepare "$project_dir" "$dependency"
compile_native flex/ml/compile.flex build/flex/control/compile-pup
build/flex/control/compile-pup flex/control/model.pup "build/flex/pixel-control-model.flex.tmp.$$"
mv -f "build/flex/pixel-control-model.flex.tmp.$$" build/flex/pixel-control-model.flex
for operation in activation binary convolution join matmul; do
    source="$project_dir/build/flex/control/kernels/$operation.flex"
    printf 'import "%s/flex/ml/kernels/ops.flex";\nfn gpu_launch_word(index) {return 0;}\nfn kernel(index,input,output,count) {if index<count {gpu_store_u32(output+index*4,vk_%s(index,input,gpu_launch_word(0),gpu_launch_word(1),gpu_launch_word(2),gpu_launch_word(3)));}return 0;}\nfn main() {return 78;}\n' "$project_dir" "$operation" > "$source"
    compile_kernel "$source" "build/flex/control/kernels/$operation.ptx"
done
compile_kernel flex/control/gradients.flex build/flex/control/kernels/gradients.ptx
compile_native flex/control/train.flex build/flex/control/trainer
compile_native flex/control/infer.flex build/flex/control/policy
compile_native flex/sim/main.flex build/flex/control/simulator
compile_native flex/control/main.flex build/flex/control/control
compile_native flex/tests/visual-control.flex build/flex/control/tests
compile_native flex/tests/visual-control-gradients.flex build/flex/control/gradient-tests
compile_native flex/tests/visual-control-policy.flex build/flex/control/policy-tests
compile_native flex/tests/visual-control-guards.flex build/flex/control/guard-tests
echo 'Built native visual-control collection, training, inference and evaluation.'
