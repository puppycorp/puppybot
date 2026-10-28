#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_dir"
bash flex/scripts/build-control.sh
if [[ -n "${1:-}" ]]; then
    test_output="$1"
    mkdir "$test_output"
else
    test_output="$(mktemp -d "$project_dir/build/flex/sim/control-tests.XXXXXXXX")"
fi
build/flex/control/tests "$test_output/contracts"
build/flex/control/highres-shape-tests
build/flex/control/large-shape-tests
build/flex/control/pose-probe-tests
bash flex/scripts/test-large-model.sh "$test_output/large-policy"
bash flex/scripts/test-dense-merge.sh "$test_output/dense-merge"
bash flex/scripts/test-empty-target-splits.sh "$project_dir/build/flex/control/prepare-targets" \
    "$project_dir/build/flex/control/empty-target-source-tests" "$project_dir/build/flex/control/merge-dense-many" \
    "$project_dir/build/flex/control/merge-targets-many" "$project_dir/build/flex/control/pose-fixtures" "$test_output/empty-target-splits"
bash flex/scripts/test-focus-sampling.sh "$test_output/focus-sampling"
bash flex/scripts/test-optimizer-limit.sh "$test_output/optimizer-limit"
bash flex/scripts/test-reversal-training.sh "$test_output/reversal-training"
bash flex/scripts/test-phase-consistency-training.sh "$test_output/phase-consistency-training"
bash flex/scripts/test-phase-balance-training.sh "$test_output/phase-balance-training"
bash flex/scripts/test-return-weight-training.sh "$test_output/return-weight-training"
bash flex/scripts/test-contact-weight-training.sh "$test_output/contact-weight-training"
bash flex/scripts/test-feedback-drop-training.sh "$test_output/feedback-drop-training"
bash flex/scripts/test-reversal-feedback-drop-training.sh "$test_output/reversal-feedback-drop-training"
bash flex/scripts/test-large-phase.sh "$test_output/large-phase"
bash flex/scripts/test-drive-feedback-ablation.sh "$project_dir/build/flex/control/ablate-drive-feedback" "$test_output/large-phase/gated-trained/weights.bin" "$test_output/drive-feedback-ablation"
bash flex/scripts/test-drive-feedback-zero.sh "$project_dir/build/flex/control/verify-drive-feedback-zero" "$test_output/large-phase/gated-trained/weights.bin" "$test_output/drive-feedback-ablation/weights.bin" "$test_output/drive-feedback-zero"
bash flex/scripts/test-drive-feedback-forward.sh "$project_dir/build/flex/control/ablate-drive-feedback" "$project_dir/build/flex/control/ablation-forward-probe" "$test_output/large-phase/gated-trained" "$test_output/large-phase/run/110330" "$test_output/drive-feedback-forward"
bash flex/scripts/test-large-memory-pose-initial.sh "$test_output/large-phase/gated-initial" "$test_output/large-memory-pose-initial"
bash flex/scripts/test-pose-memory-probe.sh "$project_dir/build/flex/control/pose-memory-probe" "$test_output/large-memory-pose-initial/policy" "$project_dir/build/flex/control/pose-probe-test-server" "$test_output/pose-memory-probe"
bash flex/scripts/test-memory-pose-analysis.sh "$project_dir/build/flex/control/pose-memory-probe" "$test_output/pose-memory-probe" "$test_output/pose-memory-analysis"
bash flex/scripts/test-phase-head-probe.sh "$test_output/large-phase/gated-trained" "$test_output/large-phase/run/110330" "$test_output/large-phase/replay/result.json" "$test_output/large-phase/original" "$test_output/phase-head-probe"
bash flex/scripts/test-evaluation-width.sh "$test_output/evaluation-width"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wait-large-phase-analysis.sh "$test_output/phase-analysis-queue"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-gated-search-disjoint.sh "$test_output/scene-disjointness"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-gated-search-pair-benchmark.sh "$test_output/gated-search-pair-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-gated-search-cohort-training.sh "$test_output/gated-search-cohort-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-student-only-pilot-training.sh "$test_output/student-only-pilot-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-student-training.sh "$test_output/coverage-student-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-teacher-training.sh "$test_output/coverage-teacher-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-focused-coverage-training.sh "$test_output/focused-coverage-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-v2-pair.sh "$test_output/coverage-v2-pair"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-v2-student-training.sh "$test_output/coverage-v2-student-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-teacher-audit.sh "$test_output/coverage-teacher-audit"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-teacher-v2-audit.sh "$test_output/coverage-teacher-v2-audit"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-benchmark-queue.sh "$test_output/coverage-benchmark-queue"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-gated-search-cohort-admission-audit.sh "$test_output/gated-search-cohort-admission-audit"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-phase-consistency-screen.sh "$test_output/phase-consistency-screen"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-balanced-phase-screen.sh "$test_output/balanced-phase-screen"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-return-weight-screen.sh "$test_output/return-weight-screen"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-return-pair.sh "$test_output/coverage-return-pair-one"
PUPPYBOT_PROJECT="$project_dir" PUPPYBOT_TEST_RETURN_PAIRS=2 bash datasets/visual-control/expanded-rooms-v1/test-coverage-return-pair.sh "$test_output/coverage-return-pair-two"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-return-benchmark.sh "$test_output/coverage-return-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-return-reversal-screen.sh "$test_output/return-reversal-screen"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-return-reversal-benchmark.sh "$test_output/return-reversal-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-contact-weight-screen.sh "$test_output/contact-weight-screen"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-contact-weight-benchmark.sh "$test_output/contact-weight-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-large-pose-screen.sh "$test_output/large-pose-screen"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-large-pose-benchmark.sh "$test_output/large-pose-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-small-pose-benchmark.sh "$test_output/small-pose-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-episode-benchmark-summary.sh "$test_output/episode-benchmark-summary"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-trajectory-diversity.sh "$test_output/trajectory-diversity"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-longer-316.sh "$test_output/longer-316"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-longer-316-benchmark.sh "$test_output/longer-316-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-queue-longer-316.sh "$test_output/queue-longer-316"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-queue-longer-316-benchmark.sh "$test_output/queue-longer-316-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-queue-large-pose-benchmark.sh "$test_output/queue-large-pose-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-diverse-development.sh "$test_output/diverse-development"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-diverse-development-benchmark.sh "$test_output/diverse-development-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-longer-diverse-development.sh "$test_output/compare-longer-diverse-development"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-blocked-feedback-summary.sh "$test_output/blocked-feedback-summary"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-contact-summary.sh "$test_output/coverage-contact-summary"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-reference-benchmark-retry.sh "$test_output/reference-benchmark-retry"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-audit-diverse-corpus.sh "$test_output/audit-diverse-corpus"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-diverse-benchmark-corpus.sh "$test_output/diverse-benchmark-corpus"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-reversal-diverse-development.sh "$test_output/reversal-diverse-development"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-scale-collection.sh "$test_output/coverage-scale-collection"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-scale-catalog.sh "$test_output/coverage-scale-catalog"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-scale-admission.sh "$test_output/coverage-scale-admission"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-scale-training.sh "$test_output/coverage-scale-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-coverage-scale-benchmark.sh "$test_output/coverage-scale-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-scale-diverse.sh "$test_output/compare-scale-diverse"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-heading-development.sh "$test_output/wide-heading-development"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-heading-smoke.sh "$test_output/wide-heading-smoke"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-heading-benchmark.sh "$test_output/wide-heading-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-student-catalog.sh "$test_output/wide-student-catalog"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-student-rollouts.sh "$test_output/wide-student-rollouts"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-audit-wide-student-control.sh "$test_output/audit-wide-student-control"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-student-admission.sh "$test_output/wide-student-admission"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-student-training.sh "$test_output/wide-student-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-wide-student.sh "$test_output/compare-wide-student"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-return-reuse-admission.sh "$test_output/return-reuse-admission"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-return-reuse-training.sh "$test_output/return-reuse-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-return-reuse.sh "$test_output/compare-return-reuse"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-return-catalog.sh "$test_output/wide-return-catalog"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-return-cohort.sh "$test_output/wide-return-cohort"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-return-admission.sh "$test_output/wide-return-admission"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-wide-return-training.sh "$test_output/wide-return-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-wide-return.sh "$test_output/compare-wide-return"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-incomplete-return-admission.sh "$test_output/incomplete-return-admission"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-incomplete-return-training.sh "$test_output/incomplete-return-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-incomplete-return.sh "$test_output/compare-incomplete-return"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-drive-feedback-ablation.sh "$test_output/compare-drive-feedback-ablation"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-neutral-drive-training.sh "$test_output/neutral-drive-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-neutral-pose-training.sh "$test_output/neutral-pose-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-neutral-drive.sh "$test_output/compare-neutral-drive"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-neutral-pose.sh "$test_output/compare-neutral-pose"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-build-forward-return-teacher.sh "$test_output/build-forward-return-teacher"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-return-box-visibility.sh "$test_output/return-box-visibility"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-forward-return-admission.sh "$test_output/forward-return-admission"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-forward-return-training.sh "$test_output/forward-return-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-forward-return-pilot.sh "$test_output/compare-forward-return-pilot"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-memory-pose-preflight.sh "$test_output/memory-pose-preflight"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-prepare-memory-pose-preflight.sh "$test_output/prepare-memory-pose-preflight"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-longer-neutral-training.sh "$test_output/longer-neutral-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-longer-neutral.sh "$test_output/compare-longer-neutral"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-reversal-neutral-training.sh "$test_output/reversal-neutral-training"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-compare-reversal-neutral.sh "$test_output/compare-reversal-neutral"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-matched-initial-inputs.sh "$test_output/matched-initial-inputs"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-long-return-cohort.sh "$test_output/long-return-cohort"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-phase-head-analysis.sh "$test_output/phase-head-analysis"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-feedback-analysis.sh "$test_output/feedback-analysis"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-feedback-drop-screen.sh "$test_output/feedback-drop-screen"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-feedback-drop-benchmark.sh "$test_output/feedback-drop-benchmark"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-gated-search-screen-analysis.sh "$test_output/gated-search-screen-analysis"
PUPPYBOT_PROJECT="$project_dir" bash datasets/visual-control/expanded-rooms-v1/test-student-only-horizon.sh "$test_output/student-only-horizon"
bash flex/scripts/test-return-progress.sh "$test_output/return-progress"
bash flex/scripts/test-demonstration-summary.sh "$project_dir/build/flex/control/summarize-demonstrations" \
    "$project_dir/build/flex/control/pose-fixtures" "$test_output/demonstration-summary"
bash flex/scripts/test-demonstrations-by-episode.sh "$project_dir/build/flex/control/summarize-demonstrations-by-episode" \
    "$project_dir/build/flex/control/summarize-demonstrations" "$project_dir/build/flex/control/pose-fixtures" "$test_output/demonstrations-by-episode"
bash flex/scripts/test-return-intervention-summary.sh "$project_dir/build/flex/control/summarize-return-interventions" \
    "$project_dir/build/flex/control/pose-fixtures" "$test_output/return-intervention-summary"
bash flex/scripts/test-search-intervention-summary.sh "$project_dir/build/flex/control/summarize-search-interventions" \
    "$project_dir/build/flex/control/pose-fixtures" "$test_output/search-intervention-summary"
bash flex/scripts/test-initial-label-ambiguity.sh "$project_dir/build/flex/control/summarize-initial-label-ambiguity" "$test_output/initial-label-ambiguity"
bash flex/scripts/test-prefix-label-ambiguity.sh "$project_dir/build/flex/control/summarize-prefix-label-ambiguity" "$test_output/prefix-label-ambiguity"
bash flex/scripts/test-initial-conflict-scenes.sh "$test_output/initial-conflict-scenes"
bash flex/scripts/test-coverage-conflict-pilot.sh "$test_output/coverage-conflict-pilot"
bash flex/scripts/test-coverage-initial-group.sh "$test_output/coverage-initial-group"
bash flex/scripts/test-coverage-prefix-group.sh "$test_output/coverage-prefix-group"
bash flex/scripts/test-expanded-data.sh "$test_output/expanded-data"
build/flex/control/heat-resolution-tests
bash flex/scripts/test-diverse-generator.sh "$test_output/diverse-rooms"
truncate -s 2147487744 "$test_output/large-highres.bin"
printf PVDAT128 | dd of="$test_output/large-highres.bin" bs=1 conv=notrunc status=none
build/flex/control/large-file-tests "$test_output/large-highres.bin" write
build/flex/control/large-file-tests "$test_output/large-highres.bin" highres
if build/flex/control/large-file-tests "$test_output/large-highres.bin" legacy > "$test_output/large-legacy.log" 2>&1; then
    echo 'Legacy file reader accepted a file above 2 GiB.' >&2
    exit 1
fi
if build/flex/control/trainer unused unused build/flex/control/kernels "$test_output/large-highres.bin" "$test_output/large-model" 0 1 100 7 --image-128 > "$test_output/large-invalid-dimensions.log" 2>&1; then
    echo 'Trainer accepted a malformed high-resolution dataset.' >&2
    exit 1
fi
[[ "$(< "$test_output/large-invalid-dimensions.log")" == *'invalid demonstration dimensions'* ]]
truncate -s 8589934593 "$test_output/excessive-highres.bin"
printf PVDAT128 | dd of="$test_output/excessive-highres.bin" bs=1 conv=notrunc status=none
if build/flex/control/large-file-tests "$test_output/excessive-highres.bin" highres > "$test_output/excessive-highres.log" 2>&1; then
    echo 'High-resolution reader accepted a file above 8 GiB.' >&2
    exit 1
fi
build/flex/control/action-tests "$test_output/action-contracts"
build/flex/control/action-weight-tests
build/flex/control/reversal-loss-tests
build/flex/control/phase-consistency-loss-tests
build/flex/control/phase-balance-loss-tests
build/flex/control/return-weight-loss-tests
build/flex/control/contact-weight-loss-tests
build/flex/control/feedback-drop-tests
if build/flex/control/feedback-drop-tests invalid > "$test_output/invalid-feedback-drop.log" 2>&1; then
    echo 'Feedback dropout accepted an invalid batch mask.' >&2
    exit 1
fi
rg -Fq 'invalid feedback mask dimensions' "$test_output/invalid-feedback-drop.log"
build/flex/control/oracle-tests "$test_output/oracle-contracts"
build/flex/control/coverage-teacher-tests
if build/flex/control/coverage-teacher-tests stale > "$test_output/stale-coverage-detection.log" 2>&1; then
    echo 'Coverage teacher accepted a stale camera detection.' >&2
    exit 1
fi
build/flex/control/motion-tests "$test_output/motion-contracts"
build/flex/control/seek-tests "$test_output/seek-contracts"
build/flex/control/seek-projection-tests
env -u PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS build/flex/control/stream-tests 45000
PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=300000 build/flex/control/stream-tests 300000
if PUPPYBOT_LOCAL_STREAM_TIMEOUT_MS=invalid build/flex/control/stream-tests 45000 > "$test_output/invalid-stream-timeout.log" 2>&1; then
    echo 'Invalid local stream timeout was accepted.' >&2
    exit 1
fi
build/flex/control/convolution-tests build/flex/control/kernels "$test_output/convolution-gradients"
bash flex/scripts/test-sequence-mirror.sh "$test_output/sequence-mirrors"
bash flex/scripts/test-stop-weight.sh "$test_output/sequence-mirrors/contracts/original.bin" "$test_output/stop-weight"
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/gradients"
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/categorical-gradients" --categorical
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/phase-gradients" --phase-gated
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/event-gradients" --phase-gated --event-aux
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/pose-gradients" --categorical --pose-aux
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/pose-event-gradients" --categorical --event-aux --pose-aux
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/target-event-gradients" --categorical --event-aux --target-aux
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/heat-event-gradients" --categorical --event-aux --heat-aux
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/heat-actor-gradients" --categorical --event-aux --heat-aux --heat-actor
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/large-phase-heat-gradients" --phase-gated --event-aux --heat-aux --heat-actor --large-model
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/large-phase-consistency-gradients" --phase-gated --event-aux --heat-aux --heat-actor --large-model --phase-consistency
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/large-phase-balance-gradients" --phase-gated --event-aux --heat-aux --heat-actor --large-model --phase-balance
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/large-return-weight-gradients" --phase-gated --event-aux --heat-aux --heat-actor --large-model --return-weight
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/large-contact-weight-gradients" --phase-gated --event-aux --heat-aux --heat-actor --large-model --contact-weight
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/large-pose-gradients" --phase-gated --event-aux --pose-aux --heat-aux --heat-actor --large-model
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/large-feedback-drop-gradients" --phase-gated --event-aux --heat-aux --heat-actor --large-model --feedback-drop
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/large-feedback-drop-pose-gradients" --phase-gated --event-aux --pose-aux --heat-aux --heat-actor --large-model --feedback-drop
build/flex/control/heat-detach-tests build/flex/control/kernels "$test_output/heat-detach-gradients"
build/flex/control/gradient-tests build/flex/control/kernels "$test_output/heat-absence-gradients" --categorical --event-aux --heat-aux --heat-actor --absence-loss
build/flex/control/guard-tests build/flex/control/trainer build/flex/control/kernels "$test_output/guards"
build/flex/control/size-tests build/flex/control/control build/flex/control/trainer build/flex/control/kernels "$test_output/size-contracts"
build/flex/control/selection-tests build/flex/control/trainer build/flex/control/kernels "$test_output/checkpoint-selection"
bash flex/scripts/test-memory-pose.sh "$test_output/memory-pose"
bash flex/scripts/test-target-position.sh "$test_output/target-position"
bash flex/scripts/test-target-heatmap.sh "$test_output/target-heatmap"
bash flex/scripts/test-target-actor.sh "$test_output/target-actor"
bash flex/scripts/test-target-detach.sh "$test_output/target-detach"
bash flex/scripts/test-target-absence.sh "$test_output/target-absence"
build/flex/control/data-tests build/flex/control/control build/flex/control/trainer build/flex/control/kernels "$test_output/data-contracts"
build/flex/control/data-tests build/flex/control/control build/flex/control/trainer build/flex/control/kernels "$test_output/event-data-contracts" --event-aux
build/flex/control/data-tests build/flex/control/control build/flex/control/trainer build/flex/control/kernels "$test_output/phase-data-contracts" --phase-from-valid
./flex/control.sh init --output "$test_output/baseline" --seed 7
build/flex/control/policy-tests "$test_output/baseline" "$test_output/policy-contracts"
./flex/control.sh collect --output "$test_output/data" --episodes 2 --validation 1 --seed 101000
./flex/control.sh verify-data --run "$test_output/data" --data "$test_output/data/data.bin" \
    --output "$test_output/verified-data"
./flex/control.sh pack-data --data "$test_output/data/data.bin" --output "$test_output/packed"
./flex/control.sh verify-data --run "$test_output/data" --data "$test_output/packed/data.bin" \
    --output "$test_output/verified-packed"
./flex/control.sh train --data "$test_output/packed/data.bin" --output "$test_output/policy" \
    --epochs 2 --batch 1 --seed 7 --from-scratch --checkpoint-every 1
if ! /usr/bin/cmp "$test_output/policy/epoch-1.bin" "$test_output/policy/first-after.bin" || \
    ! /usr/bin/cmp "$test_output/policy/epoch-2.bin" "$test_output/policy/last.bin"; then
    echo 'Periodic checkpoints differ from the corresponding optimizer state.' >&2
    exit 1
fi
bash flex/scripts/test-feedback-probe.sh "$test_output/large-phase/gated-trained" "$test_output/large-phase/run/110330" "$test_output/large-phase/replay/result.json" "$test_output/policy" "$test_output/feedback-probe"
./flex/control.sh correct --policy "$test_output/policy" --output "$test_output/corrections" \
    --episodes 2 --validation 1 --rollin 8 --horizon 300 --seed 331000
./flex/control.sh verify-data --run "$test_output/corrections" --data "$test_output/corrections/data.bin" \
    --output "$test_output/verified-corrections"
./flex/control.sh pack-data --data "$test_output/corrections/data.bin" --output "$test_output/packed-corrections"
./flex/control.sh verify-data --run "$test_output/corrections" --data "$test_output/packed-corrections/data.bin" \
    --output "$test_output/verified-packed-corrections"
./flex/control.sh train --data "$test_output/packed-corrections/data.bin" --output "$test_output/corrected-policy" \
    --initial-policy "$test_output/policy" --epochs 1 --batch 1 --seed 7
./flex/control.sh correct --policy "$test_output/corrected-policy" --output "$test_output/dense-corrections" \
    --episodes 2 --validation 1 --rollin 12 --rollin-min 4 --horizon 300 --seed 331000 --label-rollin
./flex/control.sh verify-data --run "$test_output/dense-corrections" --data "$test_output/dense-corrections/data.bin" \
    --output "$test_output/verified-dense-corrections"
./flex/control.sh pack-data --data "$test_output/dense-corrections/data.bin" --output "$test_output/packed-dense-corrections"
./flex/control.sh verify-data --run "$test_output/dense-corrections" --data "$test_output/packed-dense-corrections/data.bin" \
    --output "$test_output/verified-packed-dense-corrections"
bash flex/scripts/test-incomplete-corrections.sh "$project_dir" "$test_output/policy" \
    "$test_output/diverse-rooms/fit/26/0" "$test_output/incomplete-corrections"
bash flex/scripts/test-coverage-teacher.sh "$test_output/policy" "$test_output/diverse-rooms/fit/26/0" "$test_output/coverage-teacher"
bash flex/scripts/test-coverage-return-rollin.sh "$test_output/policy" "$test_output/coverage-return-rollin"
bash flex/scripts/test-prepared-memory-pose.sh "$test_output/coverage-return-rollin/packed/data.bin" "$test_output/coverage-return-rollin/runs" "$test_output/prepared-memory-pose"
build/flex/control/data-tests --audit-recording build/flex/control/control "$test_output/dense-corrections" \
    "$test_output/packed-dense-corrections/data.bin" "$test_output/data-audit-guards"
if ./flex/control.sh verify --run "$test_output/dense-corrections/expert-0" \
    --policy "$test_output/dense-corrections/student" --output "$test_output/rejected-oracle-student" \
    > "$test_output/rejected-oracle-student.log" 2>&1; then
    echo 'Teacher-assisted recording was accepted as an autonomous student run.' >&2
    exit 1
fi
if [[ "$(< "$test_output/rejected-oracle-student.log")" != *'student used a privileged training oracle'* || \
    -f "$test_output/rejected-oracle-student/result.json" ]]; then
    echo 'Teacher-assisted recording was not rejected for oracle access.' >&2
    exit 1
fi
./flex/control.sh train --data "$test_output/packed-dense-corrections/data.bin" --output "$test_output/dense-policy" \
    --initial-policy "$test_output/corrected-policy" --epochs 1 --batch 1 --seed 7
build/flex/control/forward-tests "$test_output/dense-policy" "$test_output/packed-dense-corrections/data.bin" "$test_output/continuous-forward"
./flex/control.sh train --data "$test_output/packed-dense-corrections/data.bin" --output "$test_output/categorical-policy" \
    --initial-policy "$test_output/dense-policy" --epochs 2 --batch 1 --seed 7 --categorical
build/flex/control/forward-tests "$test_output/categorical-policy" "$test_output/packed-dense-corrections/data.bin" "$test_output/categorical-forward"
./flex/control.sh train --data "$test_output/packed-dense-corrections/data.bin" --output "$test_output/phase-policy" \
    --initial-policy "$test_output/categorical-policy" --epochs 2 --batch 1 --seed 7 --phase-gated --event-aux
build/flex/control/forward-tests "$test_output/phase-policy" "$test_output/packed-dense-corrections/data.bin" "$test_output/phase-forward"
./flex/control.sh correct --policy "$test_output/categorical-policy" --output "$test_output/categorical-corrections" \
    --episodes 2 --validation 1 --rollin 8 --rollin-min 4 --horizon 300 --seed 331000 --label-rollin
./flex/control.sh verify-data --run "$test_output/categorical-corrections" --data "$test_output/categorical-corrections/data.bin" \
    --output "$test_output/verified-categorical-corrections"
./flex/control.sh correct --policy "$test_output/categorical-policy" --output "$test_output/return-corrections" \
    --scene "$test_output/data/expert-0/scene" --episodes 2 --validation 1 --rollin 1 --rollin-min 1 \
    --horizon 512 --seed 331100 --label-rollin --return-rollin
./flex/control.sh pack-data --data "$test_output/return-corrections/data.bin" --output "$test_output/packed-return-corrections"
./flex/control.sh verify-data --run "$test_output/return-corrections" --data "$test_output/packed-return-corrections/data.bin" \
    --output "$test_output/verified-return-corrections"
bash flex/scripts/test-return-rollin.sh "$project_dir/build/flex/control/control" "$test_output/return-corrections" \
    "$test_output/packed-return-corrections/data.bin" "$test_output/return-window-guards"
./flex/control.sh run --policy "$test_output/categorical-policy" --output "$test_output/categorical-run" \
    --episodes 1 --seed 110000 --horizon 12
./flex/control.sh verify --run "$test_output/categorical-run/110000" --policy "$test_output/categorical-run/policy" \
    --output "$test_output/verified-categorical"
./flex/control.sh run --policy "$test_output/phase-policy" --output "$test_output/phase-run" \
    --episodes 1 --seed 110000 --horizon 12
./flex/control.sh verify --run "$test_output/phase-run/110000" --policy "$test_output/phase-run/policy" \
    --output "$test_output/verified-phase"
./flex/control.sh run --policy "$test_output/dense-policy" --output "$test_output/run" \
    --episodes 1 --seed 110000 --horizon 12
./flex/control.sh verify --run "$test_output/run/110000" --policy "$test_output/run/policy" \
    --output "$test_output/verified"
if build/flex/control/simulator --headless --steps 1 --bind 127.0.0.1:0 --oracle-cache-check \
    > "$test_output/rejected-cache-check.log" 2>&1; then
    echo 'Oracle cache verification was accepted without the training oracle.' >&2
    exit 1
fi
if [[ "$(< "$test_output/rejected-cache-check.log")" != *'--oracle-cache-check requires --oracle-labels'* ]]; then
    echo 'Oracle cache verification did not enforce its training-only boundary.' >&2
    exit 1
fi
if build/flex/control/simulator --headless --case ball-into-bin --steps 1 --bind 127.0.0.1:0 \
    > "$test_output/autonomous-incomplete.log" 2>&1; then
    echo 'An incomplete autonomous case incorrectly returned success.' >&2
    exit 1
fi
if [[ "$(< "$test_output/autonomous-incomplete.log")" != *'Case incomplete:'* ]]; then
    echo 'The autonomous case failed before exercising its normal incomplete status.' >&2
    exit 1
fi
echo "Native visual-control tests passed: $test_output"
