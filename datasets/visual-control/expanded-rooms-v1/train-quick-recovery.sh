#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
base="$project/build/flex/sim/expanded-rooms-v1"
out="$base/contact-quick-v1"
probe="$base/correction-probe-v1"
pilot="$base/correction-rollin-pilot-v1"
cohort="$base/contact-cohort-v1"
[[ ! -e "$out/run.exit" && ! -e "$out/merged-10" ]]
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
printf '%s\n' "$BASHPID" > "$out/run.pid"
cd "$project"
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-before.log"
/usr/bin/sha256sum -c "$probe/screen-inputs.sha256" > "$out/screen-integrity-before.log"
[[ "$(< "$probe/run.exit")" == 0 && "$(< "$probe/screen.exit")" == 0 && "$(< "$pilot/run.exit")" == 0 && "$(< "$cohort/worker-0.exit")" == 0 ]]
sources=("$probe/subset/data.bin" "$pilot/packed/data.bin" "$cohort/packed-0/data.bin")
audits=("$probe/verified/result.json" "$pilot/verified/result.json" "$cohort/verified-0/result.json")
counts=(8 2 4)
for index in 0 1 2;do
    source_sha="$(/usr/bin/sha256sum "${sources[$index]}" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$source_sha" --argjson count "${counts[$index]}" '.passed and .episodes==$count and .datasetEpisodes==$count and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .taskEventHintAbsent' "${audits[$index]}" > /dev/null
done
/usr/bin/jq -e '.audited and (.rows|length)==4 and ([.rows[]|select(.fit)|.afterBlocked]|add)>0 and ([.rows[]|select(.fit|not)|.afterBlocked]|add)>0' "$base/contact-worker0-diagnostic-v1/result.json" > /dev/null
/usr/bin/jq -e '.episodes==8 and .auditedEpisodes==8 and .auditFailures==0' "$probe/score-screen-epoch20.json" > /dev/null
"$out/merge" "$probe/subset/data.bin" "$probe/subset" "$pilot/packed/data.bin" "$pilot/runs" "$out/merged-10" > "$out/merge-10.log" 2>&1
"$out/merge" "$out/merged-10/data.bin" "$out/merged-10" "$cohort/packed-0/data.bin" "$cohort/runs/0" "$out/merged-14" > "$out/merge-14.log" 2>&1
/usr/bin/jq -e '.episodes==14 and .fitTrajectories==10 and .sequenceLength==354 and .preservesFitValidationSplits and all(.records[];.fit==(.index<10))' "$out/merged-14/report.json" > /dev/null
"$out/preserve-data" "$probe/subset/data.bin" "$out/merged-14/data.bin" "$out/preserved-data.json" > "$out/preserve-data.log" 2>&1
/usr/bin/jq -e '.passed and .existingHistoriesPreserved==8 and .expandedHistories==14 and .expandedFittingHistories==10' "$out/preserved-data.json" > /dev/null
data="$out/merged-14/data.bin"
sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
"$out/survey" "$data" "$out/merged-14" "$out/survey.json" 14 "$sha" "$out/candidates.jsonl" > "$out/survey.log" 2>&1
candidate_sha="$(/usr/bin/sha256sum "$out/candidates.jsonl" | /usr/bin/cut -d' ' -f1)"
"$out/prepare" "$data" "$out/merged-14" "$out/candidates.jsonl" "$out/survey.json" "$sha" "$candidate_sha" "$out/targets" > "$out/prepare.log" 2>&1
"$out/preflight" "$data" "$out/targets" "$out/preflight.json" > "$out/preflight.log" 2>&1
"$out/preserve-targets" "$probe/subset/targets/targets.bin" "$out/targets/targets.bin" "$out/preserved-targets.json" > "$out/preserve-targets.log" 2>&1
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==14 and .sourceDataSHA256==$sha and .actorInputsUnchanged' "$out/preflight.json" > /dev/null
/usr/bin/jq -e '.passed and .existingHistoriesPreserved==8 and .expandedHistories==14 and .expandedFittingHistories==10' "$out/preserved-targets.json" > /dev/null
export PATH="$out/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$out/runtime"
./build/flex/control/control verify-data --run "$out/merged-14" --data "$data" --output "$out/verified" > "$out/verified.log" 2>&1
/usr/bin/jq -e --arg sha "$sha" '.passed and .episodes==14 and .datasetEpisodes==14 and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .datasetInputsMatchActualRGBAndOwnFeedback and .executedCommandsMatchRecordings and .denseOracleLabels and .taskEventHintAbsent' "$out/verified/result.json" > /dev/null
./build/flex/control/control train --initial-policy "$out/initial" --data "$data" --output "$out/model" --epochs 20 --batch 2 --learning-rate-micros 100 --seed 197 --checkpoint-every 1 --event-aux --target-heatmap "$out/targets" --heat-actor --heat-stop-gradient > "$out/train.log" 2>&1
/usr/bin/cmp "$out/initial/weights.bin" "$out/model/seed.bin"
/usr/bin/jq -e '.heatmapActorGradientDetached and .heatmapActorFeatures and .targetHeatmapAuxiliary and .cameraEventAuxiliary and (.taskFeedback|not) and .epochs==20' "$out/model/receipt.json" > /dev/null
/usr/bin/jq -s 'length==21 and .[-1].epoch==20 and .[-1].optimizerSteps==100' "$out/model/curves.jsonl" > /dev/null
./build/flex/control/forward-tests "$out/model" "$data" "$out/forward" > "$out/forward.log" 2>&1
/usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$out/forward/result.json" > /dev/null
cd "$project"
/usr/bin/bash "$probe/screen-benchmark.sh" "$out/model" screen-contact-quick-v1
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/sha256sum -c "$probe/screen-inputs.sha256" > "$out/screen-integrity-after.log"
/usr/bin/jq -s '{exploratory:true,selection:"small data subset chosen after observing development failures; checkpoint selected by demonstration validation loss",initial:.[0],continued:.[1],allEpisodeAuditsPassed:all(.[];.completedRecordings==8 and .auditedEpisodes==8 and .auditFailures==0),qualifiesForPromotion:false,retainedPolicyOverwritten:false}' "$probe/score-screen-epoch20.json" "$probe/score-screen-contact-quick-v1.json" > "$out/comparison.json"
echo 'Exploratory recovery fine-tuning and eight-case screen completed; no promotion claim.'
