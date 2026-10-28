#!/usr/bin/env bash
# Check trajectory grouping and reject changed recordings or failed audits.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
bash "$project/datasets/visual-control/expanded-rooms-v1/test-episode-benchmark-summary.sh" "$out" > /dev/null
benchmark="$out/benchmark";driver="$project/datasets/visual-control/expanded-rooms-v1/summarize-trajectory-diversity.sh"
for ((index=0;index<32;index++));do
    seed=$((9960000+index));run="$benchmark/$index/$seed";layout=$((18+index/16))
    jq --argjson layout "$layout" '.steps=2 | .leftStartRoom=false | .pathM=1 | .maxExcursionM=0.5' "$benchmark/$index/benchmark-row.json" > "$out/row.tmp";cp "$out/row.tmp" "$benchmark/$index/benchmark-row.json"
    jq --argjson layout "$layout" '.pose=[$layout,0,0]' "$run/initial.json" > "$out/initial.tmp";cp "$out/initial.tmp" "$run/initial.json"
    head -c 21168 /dev/zero > "$run/actor-295.rgb";head -c 28 /dev/zero > "$run/actor-295.feedback"
    hash="$(printf '%064d' "$((index==17 ? 1 : 0))")"
    full_hash="$(printf '%064d' "$index")"
    jq -c --arg hash "$hash" --arg full "$full_hash" '.actorSHA256=$hash | .rgbSHA256=$full | .proprio=[0,0,0,0,0,0,0] | .action=[0,1]' "$run/decisions.jsonl" > "$out/decisions.tmp";cp "$out/decisions.tmp" "$run/decisions.jsonl"
    decision_sha="$(sha256sum "$run/decisions.jsonl" | cut -d' ' -f1)"
    jq --arg sha "$decision_sha" '.decisionsSHA256=$sha' "$benchmark/$index/distance/result.json" > "$out/distance.tmp";cp "$out/distance.tmp" "$benchmark/$index/distance/result.json"
done
# The previous test deliberately leaves one bad audit.
printf '{"passed":true,"commandReplayMaxAbsError":0,"weightsSHA256":"test-sha","returnPoseChecked":true,"taskEventHintAbsent":true}\n' > "$benchmark/0/verified/result.json"
jq -s '{episodes:32,completedRecordings:32,auditedEpisodes:32,rows:sort_by(.caseIndex)}' "$benchmark/"*/benchmark-row.json > "$benchmark/score.json"
bash "$driver" "$benchmark" "$out/diversity" > "$out/diversity.log" 2>&1
jq -e '.overall.uniqueStartPoses==2 and .overall.uniqueActorTrajectories==2 and .open.uniqueActorTrajectories==1 and .hidden.uniqueActorTrajectories==2 and (.hidden.repeatedTrajectoryGroups[0].count==15) and .overall.leftStartRoom==0' "$out/diversity/summary.json" > /dev/null
printf '\001' | dd of="$benchmark/0/9960000/actor-295.rgb" bs=1 seek=0 conv=notrunc status=none
bash "$driver" "$benchmark" "$out/different-initial" > "$out/different-initial.log" 2>&1
jq -e '.overall.uniqueActorTrajectories==3 and .open.uniqueActorTrajectories==2' "$out/different-initial/summary.json" > /dev/null
head -c 21168 /dev/zero > "$benchmark/0/9960000/actor-295.rgb"
cp "$benchmark/0/9960000/decisions.jsonl" "$out/original-actor-decisions.jsonl"
printf '\n' >> "$benchmark/0/9960000/decisions.jsonl"
if bash "$driver" "$benchmark" "$out/changed-recording" > "$out/changed-recording.log" 2>&1;then echo 'Changed recording was accepted.' >&2;exit 1;fi
[[ ! -e "$out/changed-recording/summary.json" ]]
cp "$out/original-actor-decisions.jsonl" "$benchmark/0/9960000/decisions.jsonl"
decision_sha="$(sha256sum "$benchmark/0/9960000/decisions.jsonl" | cut -d' ' -f1)"
jq --arg sha "$decision_sha" '.decisionsSHA256=$sha' "$benchmark/0/distance/result.json" > "$out/distance.tmp";cp "$out/distance.tmp" "$benchmark/0/distance/result.json"
jq '.passed=false' "$benchmark/0/verified/result.json" > "$out/bad-audit.json";cp "$out/bad-audit.json" "$benchmark/0/verified/result.json"
if bash "$driver" "$benchmark" "$out/failed-audit" > "$out/failed-audit.log" 2>&1;then echo 'Failed audit was accepted.' >&2;exit 1;fi
[[ ! -e "$out/failed-audit/summary.json" ]]
echo 'Trajectory diversity groups repeated actor histories and rejects changed recordings or failed audits.'
