#!/usr/bin/env bash
# Replay audited autonomous histories and measure the training-only pose head.
set -euo pipefail
probe="$(realpath "${1:?Compiled pose probe required}")"
policy="$(realpath "${2:?Pose-supervised policy directory required}")"
out="$(realpath -m "${3:?New output directory required}")"
shift 3
(( $# > 0 ))
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
sha="$(sha256sum "$policy/weights.bin" | cut -d' ' -f1)"
sha256sum "$probe" "$policy/weights.bin" "$policy/policy" "$policy/receipt.json" > "$out/inputs.sha256"
index=0
for episode in "$@"; do
    episode="$(realpath "$episode")"
    sha256sum "$episode/initial.json" "$episode/decisions.jsonl" "$episode/../verified/result.json" >> "$out/inputs.sha256"
    find "$episode" -maxdepth 1 -type f \( -name 'actor-*.rgb' -o -name 'actor-*.feedback' \) -print0 | sort -z | xargs -0 -r sha256sum >> "$out/inputs.sha256"
    "$probe" "$policy" "$episode" "$out/$index" > "$out/$index.log" 2>&1
    jq -e --arg sha "$sha" '.weightsSHA256==$sha and .actualCommandsReplayedExactly and .physicalPoseUsedOnlyForAnalysis and .offlineReadoutOnly and .actorInputsUnchanged and .frames==(.rows|length) and .frames>0 and .returnFrames==([.rows[]|select(.actualReturning)]|length)' "$out/$index/result.json" > /dev/null
    jq --arg episode "$episode" '{episode:$episode,frames,returnFrames,meanPositionErrorM,zeroBaselineMeanPositionErrorM,meanHeadingErrorRad,returnMeanPositionErrorM,returnZeroBaselineMeanPositionErrorM,returnMeanHeadingErrorRad,exactReplay:.actualCommandsReplayedExactly}' "$out/$index/result.json" > "$out/$index-summary.json"
    index=$((index+1))
done
sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
jq -s --arg sha "$sha" '
    def weighted($value; $count): (map(select(.[$count]>0 and .[$value]!=null)) | if length==0 then null else (map(.[$value]*.[$count])|add) / (map(.[$count])|add) end);
    {weightsSHA256:$sha,episodes:length,frames:(map(.frames)|add),returnFrames:(map(.returnFrames)|add),meanPositionErrorM:weighted("meanPositionErrorM";"frames"),zeroBaselineMeanPositionErrorM:weighted("zeroBaselineMeanPositionErrorM";"frames"),returnMeanPositionErrorM:weighted("returnMeanPositionErrorM";"returnFrames"),returnZeroBaselineMeanPositionErrorM:weighted("returnZeroBaselineMeanPositionErrorM";"returnFrames"),rows:.,actorInputsUnchanged:true,physicalPoseUsedOnlyForAnalysis:true,offlineReadoutOnly:true,notCausalEvidence:true}' "$out/"*-summary.json > "$out/summary.json"
echo 'Audited autonomous trajectories replayed exactly; physical poses were used only for offline analysis.'
