#!/usr/bin/env bash
# Exclude exact duplicate case and environment files; similar rooms may remain.
set -euo pipefail
reject_known_hash() {
    local status=0
    /usr/bin/rg -Fxq "$1" "$2" || status=$?
    if (( status==0 ));then echo "Duplicate file hash: $1" >&2;exit 1;fi
    if (( status!=1 ));then echo "Could not check prior hashes: $2" >&2;exit "$status";fi
}
project="${PUPPYBOT_PROJECT:?Project root required}"
pilot="${1:?Audited search pilot required}"
corpus="${2:?Audited existing corpus required}"
coverage="${3:?Corpus coverage report required}"
out="${4:?New output directory required}"
base="$project/build/flex/sim/expanded-rooms-v1"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
[[ "$(< "$pilot/run.exit")" == 0 ]]
corpus_sha="$(/usr/bin/sha256sum "$corpus/data.bin" | /usr/bin/cut -d' ' -f1)"
pilot_sha="$(/usr/bin/sha256sum "$pilot/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
read -r n fit length < <(/usr/bin/od -An -v -tu8 -j8 -N24 "$corpus/data.bin" | /usr/bin/tr '\n' ' '; echo)
[[ "$(/usr/bin/head -c 8 "$corpus/data.bin")" == PVDATA04 && "$n" -gt 0 && "$n" -le 1024 && "$fit" -gt 0 && "$fit" -lt "$n" && "$length" -gt 0 && "$length" -le 512 && "$(/usr/bin/stat -c %s "$corpus/data.bin")" -eq $((32+n*length*21224)) ]]
/usr/bin/jq -e --arg sha "$corpus_sha" --argjson n "$n" --argjson fit "$fit" '.passed and .episodes==$n and .fittingHistories==$fit and .validationHistories==($n-$fit) and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .existingDataBytePreserved and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$coverage" > /dev/null
/usr/bin/jq -e --arg sha "$pilot_sha" '.passed and .episodes==2 and .dataSHA256==$sha and .teacherLabelsTrainingOnly and (.actorTaskEventHint) == false and (.studentAutonomousSuccessClaimed|not) and (.automaticMerge|not)' "$pilot/summary.json" > /dev/null
/usr/bin/jq -e --arg sha "$pilot_sha" '.passed and .episodes==2 and .dataSHA256==$sha and .studentRollinMaxAbsError==0 and .denseOracleLabels and .taskEventHintAbsent' "$pilot/verified/result.json" > /dev/null
/usr/bin/sha256sum "$corpus/data.bin" "$coverage" "$pilot/packed/data.bin" "$pilot/summary.json" "$pilot/verified/result.json" > "$out/inputs.sha256"
for ((index=0;index<n;index++));do
    for file in case.json environment.bin;do /usr/bin/sha256sum "$corpus/expert-$index/scene/$file" | /usr/bin/tee -a "$out/scene-inputs.sha256" | /usr/bin/cut -d' ' -f1;done
done > "$out/prior-hashes.txt"
for layout in 18 19;do
    for scene in {0..15};do for file in case.json environment.bin;do /usr/bin/sha256sum "$base/unseen-benchmark-v2/scenes/$layout/$scene/$file" | /usr/bin/tee -a "$out/scene-inputs.sha256" | /usr/bin/cut -d' ' -f1;done;done
done >> "$out/prior-hashes.txt"
for layout in 20 21 22 23;do
    for scene in {0..15};do for file in case.json environment.bin;do /usr/bin/sha256sum "$base/generalization-benchmark-v1/scenes/$layout/$scene/$file" | /usr/bin/tee -a "$out/scene-inputs.sha256" | /usr/bin/cut -d' ' -f1;done;done
done >> "$out/prior-hashes.txt"
for episode in 0 1;do
    scene="$pilot/catalog/$episode"; layout=49; role=true
    if (( episode ));then layout=149;role=false;fi
    /usr/bin/jq -e --argjson layout "$layout" --argjson role "$role" '.layoutId==$layout and .fit==$role' "$scene/layout.json" > /dev/null
    for file in case.json environment.bin;do
        /usr/bin/cmp "$scene/$file" "$pilot/runs/expert-$episode/scene/$file"
        digest="$(/usr/bin/sha256sum "$scene/$file" | /usr/bin/cut -d' ' -f1)"
        reject_known_hash "$digest" "$out/prior-hashes.txt"
        printf '%s\n' "$digest" >> "$out/prior-hashes.txt"
        /usr/bin/sha256sum "$scene/$file" >> "$out/inputs.sha256"
    done
done
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
/usr/bin/sha256sum -c "$out/scene-inputs.sha256" > "$out/scene-integrity-after.log"
/usr/bin/jq -n --arg corpus "$corpus_sha" --arg pilot "$pilot_sha" --argjson n "$n" '{passed:true,existingHistories:$n,corpusDataSHA256:$corpus,pilotDataSHA256:$pilot,pilotHistories:2,exactCasesAndEnvironmentsDisjointFromCorpusDevelopmentAndGeneralization:true,similarGeometryNotExcluded:true,reservedFinalNotGenerated:true,automaticMerge:false}' > "$out/result.json"
echo 'Pilot scenes are disjoint by exact file hash from the corpus and evaluation scenes.'
