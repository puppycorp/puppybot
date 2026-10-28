#!/usr/bin/env bash
# Independently recheck development scenes against every admitted history.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
corpus="${1:?Audited corpus required}"
coverage="${2:?Corpus coverage required}"
out="${3:?New output directory required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
sha="$(/usr/bin/sha256sum "$corpus/data.bin" | /usr/bin/cut -d' ' -f1)"
read -r n fit length < <(/usr/bin/od -An -v -tu8 -j8 -N24 "$corpus/data.bin" | /usr/bin/tr '\n' ' '; echo)
[[ "$(/usr/bin/head -c 8 "$corpus/data.bin")" == PVDATA04 && "$n" -gt 0 && "$n" -le 1024 && "$fit" -gt 0 && "$fit" -lt "$n" && "$length" -gt 0 && "$length" -le 512 && "$(/usr/bin/stat -c %s "$corpus/data.bin")" -eq $((32+n*length*21224)) ]]
/usr/bin/jq -e --arg sha "$sha" --argjson n "$n" --argjson fit "$fit" '.passed and .episodes==$n and .fittingHistories==$fit and .validationHistories==($n-$fit) and .dataSHA256==$sha and .newHistoriesIndependentlyAudited and .existingDataBytePreserved and .teacherLabelsTrainingOnly and .actorInputsUnchanged' "$coverage" > /dev/null
for ((index=0;index<n;index++));do
    scene="$corpus/expert-$index/scene"
    casehash="$(/usr/bin/sha256sum "$scene/case.json" | /usr/bin/tee -a "$out/scene-inputs.sha256" | /usr/bin/cut -d' ' -f1)"
    envhash="$(/usr/bin/sha256sum "$scene/environment.bin" | /usr/bin/tee -a "$out/scene-inputs.sha256" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -n --argjson index "$index" --argjson fit "$((index<fit))" --arg case "$casehash" --arg environment "$envhash" '{index:$index,fit:($fit==1),caseSHA256:$case,environmentSHA256:$environment}'
done > "$out/corpus.jsonl"
scenes="$project/build/flex/sim/expanded-rooms-v1/unseen-benchmark-v2/scenes"
for layout in 18 19;do
    for scene in {0..15};do
        dir="$scenes/$layout/$scene"
        casehash="$(/usr/bin/sha256sum "$dir/case.json" | /usr/bin/tee -a "$out/scene-inputs.sha256" | /usr/bin/cut -d' ' -f1)"
        envhash="$(/usr/bin/sha256sum "$dir/environment.bin" | /usr/bin/tee -a "$out/scene-inputs.sha256" | /usr/bin/cut -d' ' -f1)"
        /usr/bin/jq -n --argjson layout "$layout" --argjson scene "$scene" --arg case "$casehash" --arg environment "$envhash" '{layout:$layout,scene:$scene,caseSHA256:$case,environmentSHA256:$environment}'
    done
done > "$out/development.jsonl"
/usr/bin/jq -n --arg sha "$sha" --argjson n "$n" --argjson fit "$fit" --slurpfile corpus "$out/corpus.jsonl" --slurpfile dev "$out/development.jsonl" '
    [$corpus[]|select(.fit)] as $training | [$corpus[]|select(.fit|not)] as $validation |
    [$dev[]|select(.caseSHA256 as $h | any($corpus[]; .caseSHA256==$h))] as $caseOverlap |
    [$dev[]|select(.environmentSHA256 as $h | any($corpus[]; .environmentSHA256==$h))] as $envOverlap |
    [$validation[]|select(.caseSHA256 as $h | any($training[]; .caseSHA256==$h))] as $validationCaseOverlap |
    [$validation[]|select(.environmentSHA256 as $h | any($training[]; .environmentSHA256==$h))] as $validationEnvOverlap |
    {passed:(($caseOverlap|length)==0 and ($envOverlap|length)==0 and ($dev|length)==32),corpusDataSHA256:$sha,histories:$n,fittingHistories:$fit,developmentCases:($dev|length),developmentCaseOverlap:($caseOverlap|length),developmentEnvironmentOverlap:($envOverlap|length),validationHistoriesSharingCaseWithFit:($validationCaseOverlap|length),validationHistoriesSharingEnvironmentWithFit:($validationEnvOverlap|length),exactFileHashesOnly:true,similarGeometryNotExcluded:true}' > "$out/report.json"
/usr/bin/jq -e '.passed' "$out/report.json" > /dev/null
/usr/bin/sha256sum -c "$out/scene-inputs.sha256" > "$out/scene-integrity-after.log"
[[ "$(/usr/bin/sha256sum "$corpus/data.bin" | /usr/bin/cut -d' ' -f1)" == "$sha" ]]
/usr/bin/mv "$out/report.json" "$out/result.json"
echo 'Development cases and environments are disjoint from the corpus by exact file hash.'
