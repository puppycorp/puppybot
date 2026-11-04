#!/usr/bin/env bash
# Verify aggregation on a replay fixture and reject a changed actor image.
set -euo pipefail
probe="$(realpath "${1:?Pose probe required}")"
fixture="$(realpath "${2:?Completed synthetic probe fixture required}")"
out="$(realpath -m "${3:?New output directory required}")"
[[ ! -e "$out" ]]
mkdir "$out"
cp -a "$fixture/episode" "$out/episode"
cp "$fixture/original.jsonl" "$out/episode/run/decisions.jsonl"
cp "$out/episode/run/actor-0.rgb" "$out/episode/run/actor-10.rgb"
analysis="$(cd "$(dirname "$0")/../.." && pwd)/datasets/visual-control/expanded-rooms-v1/analyze-memory-pose.sh"
"$analysis" "$probe" "$fixture/policy" "$out/good" "$out/episode/run" "$out/episode/run" > "$out/good.log" 2>&1
jq -e '.episodes==2 and .frames==4 and .returnFrames==2 and .actorInputsUnchanged and .physicalPoseUsedOnlyForAnalysis and .offlineReadoutOnly and .notCausalEvidence and (.rows|length)==2 and .zeroBaselineMeanPositionErrorM==0.5 and .returnZeroBaselineMeanPositionErrorM==1' "$out/good/summary.json" > /dev/null
printf '\001' | dd of="$out/episode/run/actor-10.rgb" bs=1 seek=0 conv=notrunc status=none
if "$analysis" "$probe" "$fixture/policy" "$out/bad" "$out/episode/run" > "$out/bad.log" 2>&1; then
    echo 'Memory-pose analysis accepted a changed image.' >&2; exit 1
fi
[[ "$(< "$out/bad/run.exit")" != 0 && ! -e "$out/bad/summary.json" ]]
rg -Fq 'pose probe RGB differs from recorded frame hash' "$out/bad/0.log"
echo 'Memory-pose analysis aggregates aligned replays and rejects changed images.'
