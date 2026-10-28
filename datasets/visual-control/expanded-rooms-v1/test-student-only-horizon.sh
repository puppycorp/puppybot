#!/usr/bin/env bash
# Synthetic metadata migration and provenance test; no simulator is run.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(/usr/bin/realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]
mock="$out/mock";base="$mock/build/flex/sim/expanded-rooms-v1";root="$base/large-model-v1";pilot="$root/student-only-search-pilot-v1";runtime="$root/incomplete-correction-tests-v4/runtime"
mkdir -p "$pilot/packed" "$pilot/verified" "$pilot/runs/expert-0" "$pilot/runs/expert-1" "$runtime/build/flex/control" "$base/unseen-benchmark-v2/native-path"
truncate -s $((32+2*300*21224)) "$pilot/packed/data.bin"
printf 'PVDATA03\002\000\000\000\000\000\000\000\001\000\000\000\000\000\000\000\054\001\000\000\000\000\000\000' | dd of="$pilot/packed/data.bin" conv=notrunc status=none
sha="$(/usr/bin/sha256sum "$pilot/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
cp --reflink=auto "$pilot/packed/data.bin" "$pilot/runs/data.bin"
/usr/bin/jq -n --arg sha "$sha" '{episodes:2,sourceSHA256:$sha,dataSHA256:$sha,originalSequenceLength:300,sequenceLength:300,completeHistoriesPreserved:true,onlyTrailingPaddingRemoved:true}' > "$pilot/packed/report.json"
printf '0\n' > "$pilot/run.exit"
/usr/bin/jq -n --arg sha "$sha" '{passed:true,episodes:2,dataSHA256:$sha,denseOracleLabels:true,teacherLabelsTrainingOnly:true,studentAutonomousSuccessClaimed:false}' > "$pilot/summary.json"
/usr/bin/jq -n --arg sha "$sha" '{passed:true,episodes:2,dataSHA256:$sha,studentRollinMaxAbsError:0,denseOracleLabels:true,taskEventHintAbsent:true,incompleteEpisodesClaimedSuccessful:false}' > "$pilot/verified/result.json"
for episode in 0 1;do printf '{"allowIncomplete":true,"studentStartAction":0,"scheduledRollinActions":300,"maximumRollinActions":300,"studentActions":300,"terminationReason":"horizon"}\n' > "$pilot/runs/expert-$episode/supervision.json";done
cat > "$runtime/build/flex/control/control" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == verify-data ]];shift
while (( $# ));do case "$1" in --data) data="$2";shift 2;; --output) output="$2";shift 2;; *) shift;; esac;done
mkdir "$output";sha="$(/usr/bin/sha256sum "$data" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg sha "$sha" '{passed:true,episodes:2,dataSHA256:$sha,studentRollinMaxAbsError:0,denseOracleLabels:true,zeroPaddingChecked:true,taskEventHintAbsent:true,incompleteEpisodesClaimedSuccessful:false}' > "$output/result.json"
EOF
chmod +x "$runtime/build/flex/control/control"
driver="$project/datasets/visual-control/expanded-rooms-v1/annotate-student-only-horizon.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_STUDENT_HORIZON_OUT="$out/good" /usr/bin/bash "$driver" > "$out/good.log" 2>&1
/usr/bin/jq -e '.passed and .recordedHorizon==300 and .horizonDerivedFromOriginalDataHeader and .originalMetadataUnchanged and .replayVerified' "$out/good/result.json" > /dev/null
/usr/bin/jq -e '.recordedHorizon==300' "$out/good/runs/expert-0/supervision.json" > /dev/null
/usr/bin/jq -e 'has("recordedHorizon")|not' "$pilot/runs/expert-0/supervision.json" > /dev/null
/usr/bin/jq '.recordedHorizon=301' "$pilot/runs/expert-0/supervision.json" > "$out/meta.json";mv "$out/meta.json" "$pilot/runs/expert-0/supervision.json"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_STUDENT_HORIZON_OUT="$out/bad" /usr/bin/bash "$driver" > "$out/bad.log" 2>&1;then echo 'Conflicting recorded horizon was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" == 1 && ! -e "$out/bad/result.json" ]]
echo 'Synthetic horizon migration preserves source metadata and rejects conflicts.'
