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

mkdir -p build/flex/control/kernels build/flex/control/kernels-rdna build/flex/control/compiler-source build/flex/sim
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
# The direct RDNA encoder lacks correctly rounded FP32 divide/sqrt. Staged
# copies use the exact integer-corrected operations.
compile_rdna_kernel() {
    local input="$1" output="$2"
    local staged="build/flex/control/kernels-rdna/$(basename "$input")"
    sed -e "s#^import \".*ml/kernels/ops.flex\";#import \"$project_dir/src/ml/kernels/ops-rdna.flex\";#" \
        -e '/^fn gpu_f32_sqrt(value) /d' -e 's/gpu_f32_sqrt(/vk_sqrt_exact(/g' \
        "$input" > "$staged"
    if grep -q 'gpu_f32_sqrt\|ml/kernels/ops.flex' "$staged"; then
        echo "RDNA staging left an unsupported operation in $input." >&2
        exit 1
    fi
    "$compiler" --target rdna-gfx1201 "$staged" -o "$output.tmp.$$"
    mv -f "$output.tmp.$$" "$output"
}
stage="$project_dir/build/flex/control/compiler-source"
for directory in compiler vm lib; do
    mkdir -p "$stage/$directory"
    cp -a "$dependency/$directory/." "$stage/$directory/"
done
# rdna.patch adds the direct RDNA encoder's 32-bit shared-memory loads and stores.
for patch_file in "$project_dir/src/compiler/gpu-inference.patch" "$project_dir/src/compiler/rdna.patch"; do
    if patch --batch --dry-run --forward -p1 -d "$stage" -i "$patch_file" >/dev/null 2>&1; then
        patch --batch --forward -p1 -d "$stage" -i "$patch_file" >/dev/null
    elif ! patch --batch --dry-run --reverse -p1 -d "$stage" -i "$patch_file" >/dev/null 2>&1; then
        echo "GPU compiler patch $(basename "$patch_file") does not match the selected dependency." >&2
        exit 1
    fi
done
compiler="$project_dir/build/flex/control/compiler"
"$bootstrap" "$stage/compiler/main.flex" -o "$compiler.tmp"
mv -f "$compiler.tmp" "$compiler"

# Import adapters contain native Flexscript paths; no Python generators run.
printf 'import "%s/lib/device.flex";\n' "$dependency" > build/flex/pup-device.flex
printf 'import "%s/libs/ml/pup/parser.flex";\n' "$dependency" > build/flex/pup-parser.flex
printf 'import "%s/libs/ml/pup/gpu/kernels/ops-body.flex";\n' "$dependency" > build/flex/pup-kernel-ops.flex
sed -e '/^lowering vk_div "f32.div";$/d' \
    -e 's/^fn vk_div(a,b) {return vk_pack_f32(f64_div(vk_unpack_f32(a),vk_unpack_f32(b)));}$/fn vk_div(a,b) {return vk_div_exact(a,b);}/' \
    -e 's/^fn vk_quotient(a,b) {$/fn vk_quotient_f64(a,b) {/' \
    -e 's/^fn gpu_f32_from_i64(value) {return \(.*\)}$/fn gpu_f32_from_i64(value) {if value>=0 \&\& value<0x1000000 {return vr_index_f32(value);}return \1}/' \
    "$dependency/libs/ml/pup/gpu/kernels/ops-body.flex" > build/flex/pup-kernel-ops-rdna.flex
if grep -q 'f32\.div\|f64_div' build/flex/pup-kernel-ops-rdna.flex || ! grep -q '^fn vk_quotient_f64(a,b) {$' build/flex/pup-kernel-ops-rdna.flex \
    || ! grep -q '^fn gpu_f32_from_i64(value) {if value>=0' build/flex/pup-kernel-ops-rdna.flex; then
    echo 'Kernel operations no longer match the RDNA divide and index adapters.' >&2
    exit 1
fi
printf 'import "%s/libs/ml/pup/gpu/kernels/pack.flex";\n' "$dependency" > build/flex/pup-kernel-pack.flex
compile_native src/control/prepare.flex build/flex/control/prepare
build/flex/control/prepare "$project_dir" "$dependency"
compile_native src/ml/compile.flex build/flex/control/compile-pup
build/flex/control/compile-pup src/control/model.pup "build/flex/pixel-control-model.flex.tmp.$$"
mv -f "build/flex/pixel-control-model.flex.tmp.$$" build/flex/pixel-control-model.flex
build/flex/control/compile-pup src/control/model-categorical.pup "build/flex/pixel-control-categorical-model.flex.tmp.$$"
mv -f "build/flex/pixel-control-categorical-model.flex.tmp.$$" build/flex/pixel-control-categorical-model.flex
build/flex/control/compile-pup src/control/model-categorical-phase.pup "build/flex/pixel-control-categorical-phase-model.flex.tmp.$$"
mv -f "build/flex/pixel-control-categorical-phase-model.flex.tmp.$$" build/flex/pixel-control-categorical-phase-model.flex
build/flex/control/compile-pup src/control/model-categorical-heat.pup "build/flex/pixel-control-categorical-heat-model.flex.tmp.$$"
mv -f "build/flex/pixel-control-categorical-heat-model.flex.tmp.$$" build/flex/pixel-control-categorical-heat-model.flex
build/flex/control/compile-pup src/control/model-categorical-heat-128.pup "build/flex/pixel-control-categorical-heat-128-model.flex.tmp.$$"
mv -f "build/flex/pixel-control-categorical-heat-128-model.flex.tmp.$$" build/flex/pixel-control-categorical-heat-128-model.flex
build/flex/control/compile-pup src/control/model-categorical-large.pup "build/flex/pixel-control-categorical-large-model.flex.tmp.$$"
mv -f "build/flex/pixel-control-categorical-large-model.flex.tmp.$$" build/flex/pixel-control-categorical-large-model.flex
build/flex/control/compile-pup src/control/model-categorical-heat-large.pup "build/flex/pixel-control-categorical-heat-large-model.flex.tmp.$$"
mv -f "build/flex/pixel-control-categorical-heat-large-model.flex.tmp.$$" build/flex/pixel-control-categorical-heat-large-model.flex
build/flex/control/compile-pup src/control/model-categorical-heat-phase-large.pup "build/flex/pixel-control-categorical-heat-phase-large-model.flex.tmp.$$"
mv -f "build/flex/pixel-control-categorical-heat-phase-large-model.flex.tmp.$$" build/flex/pixel-control-categorical-heat-phase-large-model.flex
for operation in activation binary convolution join matmul; do
    source="$project_dir/build/flex/control/kernels/$operation.flex"
    printf 'import "%s/src/ml/kernels/ops.flex";\nfn gpu_launch_word(index) {return 0;}\nfn kernel(index,input,output,count) {if index<count {gpu_store_u32(output+index*4,vk_%s(index,input,gpu_launch_word(0),gpu_launch_word(1),gpu_launch_word(2),gpu_launch_word(3)));}return 0;}\nfn main() {return 78;}\n' "$project_dir" "$operation" > "$source"
    compile_kernel "$source" "build/flex/control/kernels/$operation.ptx"
    compile_rdna_kernel "$source" "build/flex/control/kernels/$operation.hip"
done
compile_kernel src/control/gradients.flex build/flex/control/kernels/gradients.ptx
compile_kernel src/control/recurrence.flex build/flex/control/kernels/recurrence.ptx
compile_kernel src/control/recurrence-backward.flex build/flex/control/kernels/recurrence-backward.ptx
compile_kernel src/control/recurrence-registers.flex build/flex/control/kernels/recurrence-registers.ptx
compile_kernel src/control/recurrence-registers-backward.flex build/flex/control/kernels/recurrence-registers-backward.ptx
compile_kernel src/control/convolution-train.flex build/flex/control/kernels/convolution-train.ptx
compile_kernel src/control/binary-train.flex build/flex/control/kernels/binary-train.ptx
for kernel in gradients recurrence recurrence-backward convolution-train binary-train matmul-train convolution-pairs; do
    compile_rdna_kernel "src/control/$kernel.flex" "build/flex/control/kernels/$kernel.hip"
done
# One weight per register exceeds RDNA's 256 VGPRs; these keep two per 64-bit local.
compile_rdna_kernel src/control/recurrence-registers-rdna.flex build/flex/control/kernels/recurrence-registers.hip
compile_rdna_kernel src/control/recurrence-registers-backward-rdna.flex build/flex/control/kernels/recurrence-registers-backward.hip
compile_native src/control/train.flex build/flex/control/trainer
compile_native src/control/infer.flex build/flex/control/policy
compile_native src/control/infer-categorical.flex build/flex/control/policy-categorical
compile_native src/control/infer-categorical-phase.flex build/flex/control/policy-categorical-phase
compile_native src/control/infer-categorical-heat.flex build/flex/control/policy-categorical-heat
compile_native src/control/infer-categorical-heat-128.flex build/flex/control/policy-categorical-heat-128
compile_native src/control/infer-categorical-large.flex build/flex/control/policy-categorical-large
compile_native src/control/infer-categorical-heat-large.flex build/flex/control/policy-categorical-heat-large
compile_native src/control/infer-categorical-heat-phase-large.flex build/flex/control/policy-categorical-heat-phase-large
compile_native src/sim/main.flex build/flex/control/simulator
compile_native src/control/main.flex build/flex/control/control
compile_native src/control/ablate-drive-feedback.flex build/flex/control/ablate-drive-feedback
compile_native src/control/verify-drive-feedback-zero.flex build/flex/control/verify-drive-feedback-zero
compile_native datasets/visual-control/expanded-rooms-v1/ablation-forward-probe.flex build/flex/control/ablation-forward-probe
compile_native src/tests/visual-control.flex build/flex/control/tests
compile_native src/tests/visual-control-highres-shape.flex build/flex/control/highres-shape-tests
compile_native src/tests/visual-control-large-shape.flex build/flex/control/large-shape-tests
compile_native src/tests/visual-control-large-forward.flex build/flex/control/large-forward-tests
compile_native src/tests/visual-control-large-phase-initial.flex build/flex/control/large-phase-initial-tests
compile_native src/tests/visual-control-highres-infer.flex build/flex/control/highres-infer-tests
compile_native src/tests/visual-control-highres-forward.flex build/flex/control/highres-forward-tests
compile_native src/tests/visual-control-large-file.flex build/flex/control/large-file-tests
compile_native src/tests/visual-control-heat-resolution.flex build/flex/control/heat-resolution-tests
compile_native datasets/visual-control/expanded-rooms-v1/generate-diverse.flex build/flex/control/diverse-generator
compile_native datasets/visual-control/expanded-rooms-v1/measure-brick-distance.flex build/flex/control/measure-brick-distance
compile_native datasets/visual-control/expanded-rooms-v1/merge-dense-many.flex build/flex/control/merge-dense-many
compile_native datasets/visual-control/expanded-rooms-v1/summarize-demonstrations.flex build/flex/control/summarize-demonstrations
compile_native datasets/visual-control/expanded-rooms-v1/summarize-demonstrations-by-episode.flex build/flex/control/summarize-demonstrations-by-episode
compile_native datasets/visual-control/expanded-rooms-v1/summarize-return-interventions.flex build/flex/control/summarize-return-interventions
compile_native datasets/visual-control/expanded-rooms-v1/summarize-search-interventions.flex build/flex/control/summarize-search-interventions
compile_native datasets/visual-control/expanded-rooms-v1/summarize-initial-label-ambiguity.flex build/flex/control/summarize-initial-label-ambiguity
compile_native datasets/visual-control/expanded-rooms-v1/summarize-prefix-label-ambiguity.flex build/flex/control/summarize-prefix-label-ambiguity
compile_native datasets/visual-control/expanded-rooms-v1/coverage-initial-query.flex build/flex/control/coverage-initial-query
compile_native datasets/visual-control/expanded-rooms-v1/coverage-replay-query.flex build/flex/control/coverage-replay-query
compile_native src/tests/visual-control-dataset-limit.flex build/flex/control/dataset-limit-tests
compile_native datasets/visual-control/expanded-rooms-v1/merge-targets-two.flex build/flex/control/merge-targets-two
compile_native datasets/visual-control/expanded-rooms-v1/merge-targets-many.flex build/flex/control/merge-targets-many
compile_native datasets/visual-control/expanded-rooms-v1/prepare-targets.flex build/flex/control/prepare-targets
compile_native src/tests/visual-control-empty-target-source.flex build/flex/control/empty-target-source-tests
compile_native datasets/visual-control/expanded-rooms-v1/target-preserve-added.flex build/flex/control/target-preserve-added
compile_native datasets/visual-control/expanded-rooms-v1/data-preserve-added.flex build/flex/control/data-preserve-added
compile_native datasets/visual-control/expanded-rooms-v1/preflight-expanded-targets.flex build/flex/control/preflight-expanded-targets
compile_native datasets/visual-control/expanded-rooms-v1/publish-large-checkpoint.flex build/flex/control/publish-large-checkpoint
compile_native datasets/visual-control/return-recovery-v1/merge.flex build/flex/control/merge-dense-reference
compile_native src/tests/visual-control-diverse-scenes.flex build/flex/control/diverse-scene-tests
compile_native src/tests/visual-control-protocol-parity.flex build/flex/control/protocol-parity-tests
compile_native src/tests/visual-control-gradients.flex build/flex/control/gradient-tests
compile_native src/tests/visual-control-policy.flex build/flex/control/policy-tests
compile_native src/tests/visual-control-guards.flex build/flex/control/guard-tests
compile_native src/tests/visual-control-progress-guard.flex build/flex/control/progress-guard-tests
compile_native src/tests/visual-control-size.flex build/flex/control/size-tests
compile_native src/tests/visual-control-selection.flex build/flex/control/selection-tests
compile_native src/tests/visual-control-pose-data.flex build/flex/control/pose-fixtures
compile_native src/tests/visual-control-target-data.flex build/flex/control/target-fixtures
compile_native src/tests/visual-control-target-zero.flex build/flex/control/target-zero
compile_native src/tests/visual-control-initial-parity.flex build/flex/control/initial-parity
compile_native datasets/visual-control/target-actor-v1/publish.flex build/flex/control/heat-actor-publish
compile_native src/tests/visual-control-heat-detach.flex build/flex/control/heat-detach-tests
compile_native datasets/visual-control/target-detach-v1/publish.flex build/flex/control/heat-detach-publish
compile_native datasets/visual-control/target-absence-v1/publish.flex build/flex/control/heat-absence-publish
compile_native src/tests/visual-control-pose-compare.flex build/flex/control/pose-compare
compile_native datasets/visual-control/odometry-aux-v1/core-match.flex build/flex/control/pose-core-match
compile_native src/tests/visual-control-data.flex build/flex/control/data-tests
compile_native src/tests/visual-control-actions.flex build/flex/control/action-tests
compile_native src/tests/visual-control-forward.flex build/flex/control/forward-tests
compile_native src/tests/visual-control-convolution.flex build/flex/control/convolution-tests
compile_native src/tests/visual-control-augmentation.flex build/flex/control/augmentation-tests
compile_native src/tests/visual-control-oracle.flex build/flex/control/oracle-tests
compile_native src/tests/visual-control-coverage-teacher.flex build/flex/control/coverage-teacher-tests
compile_native src/tests/visual-control-motion.flex build/flex/control/motion-tests
compile_native src/tests/visual-control-seek.flex build/flex/control/seek-tests
compile_native src/tests/sim-seek-projection.flex build/flex/control/seek-projection-tests
compile_native src/tests/visual-control-stream.flex build/flex/control/stream-tests
compile_native src/tests/visual-control-action-weight.flex build/flex/control/action-weight-tests
compile_native src/tests/visual-control-reversal-loss.flex build/flex/control/reversal-loss-tests
compile_native src/tests/visual-control-phase-consistency-loss.flex build/flex/control/phase-consistency-loss-tests
compile_native src/tests/visual-control-phase-balance-loss.flex build/flex/control/phase-balance-loss-tests
compile_native src/tests/visual-control-return-weight-loss.flex build/flex/control/return-weight-loss-tests
compile_native src/tests/visual-control-contact-weight-loss.flex build/flex/control/contact-weight-loss-tests
compile_native src/tests/visual-control-feedback-drop.flex build/flex/control/feedback-drop-tests
compile_native src/tests/visual-control-pose-open.flex build/flex/control/pose-open-tests
compile_native datasets/visual-control/expanded-rooms-v1/prepare-memory-pose.flex build/flex/control/prepare-memory-pose
compile_native datasets/visual-control/expanded-rooms-v1/compare-pose-initial.flex build/flex/control/compare-pose-initial
compile_native datasets/visual-control/expanded-rooms-v1/large-phase-head-probe.flex build/flex/control/large-phase-head-probe
compile_native datasets/visual-control/expanded-rooms-v1/pose-memory-probe.flex build/flex/control/pose-memory-probe
compile_native src/tests/visual-control-pose-probe.flex build/flex/control/pose-probe-tests
compile_native src/tests/visual-control-pose-probe-server.flex build/flex/control/pose-probe-test-server
compile_native datasets/visual-control/expanded-rooms-v1/large-feedback-probe.flex build/flex/control/large-feedback-probe
echo 'Built native visual-control collection, training, inference and evaluation.'
