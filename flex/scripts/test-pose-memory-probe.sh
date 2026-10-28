#!/usr/bin/env bash
# Exercise pre-action pose alignment and exact replay with a synthetic server.
set -euo pipefail
probe="$(realpath "${1:?Pose probe executable required}")"
pose_policy="$(realpath "${2:?Large pose-supervised policy required}")"
server="$(realpath "${3:?Synthetic actor server required}")"
out="$(realpath -m "${4:?New output directory required}")";[[ ! -e "$out" ]];mkdir -p "$out/policy/kernels" "$out/episode/verified" "$out/episode/run"
cp "$pose_policy/weights.bin" "$out/policy/weights.bin"
cp "$server" "$out/policy/policy"
sha="$(sha256sum "$out/policy/weights.bin" | cut -d' ' -f1)";binary="$(sha256sum "$out/policy/policy" | cut -d' ' -f1)"
jq -n --arg sha "$sha" --arg binary "$binary" '{weightsSHA256:$sha,binarySHA256:$binary,memoryPoseAuxiliary:true,phaseGatedNavigation:true,memoryWidth:256,taskFeedback:false}' > "$out/policy/receipt.json"
jq -n --arg sha "$sha" '{passed:true,commandReplayMaxAbsError:0,returnPoseChecked:true,taskEventHintAbsent:true,weightsSHA256:$sha}' > "$out/episode/verified/result.json"
run="$out/episode/run";jq -n '{pose:[0,0,0],totalSteps:0,findReturn:{consumedIndex:-1}}' > "$run/initial.json"
dd if=/dev/zero of="$run/actor-0.rgb" bs=21168 count=1 status=none;cp "$run/actor-0.rgb" "$run/actor-10.rgb"
dd if=/dev/zero of="$run/actor-0.feedback" bs=28 count=1 status=none;cp "$run/actor-0.feedback" "$run/actor-10.feedback"
frame_sha="$(sha256sum "$run/actor-10.rgb" | cut -d' ' -f1)"
jq -nc --arg sha "$frame_sha" '{step:10,action:[0,1],proprio:[0,0,0,0,0,0,0],actorSHA256:$sha,state:{pose:[1,0,0],findReturn:{consumedIndex:0}}},{step:20,action:[0,1],proprio:[0,0,0,0,0,0,0],actorSHA256:$sha,state:{pose:[2,0,0],findReturn:{consumedIndex:0}}}' > "$run/decisions.jsonl"
"$probe" "$out/policy" "$run" "$out/good" > "$out/good.log" 2>&1
jq -e --arg sha "$sha" '.weightsSHA256==$sha and .frames==2 and .returnFrames==1 and .actualCommandsReplayedExactly and .physicalPoseUsedOnlyForAnalysis and .offlineReadoutOnly and .actorInputsUnchanged and (.rows|length)==2 and .rows[0].target==[0,0,0,1] and .rows[1].target==[0.125,0,0,1] and (.rows[0].actualReturning|not) and .rows[1].actualReturning and all(.rows[];.actionClass==1)' "$out/good/result.json" > /dev/null
cp "$run/decisions.jsonl" "$out/original.jsonl";jq -c 'if .step==10 then .action=[0,-1] else . end' "$out/original.jsonl" > "$run/decisions.jsonl"
if "$probe" "$out/policy" "$run" "$out/bad-action" > "$out/bad-action.log" 2>&1;then echo 'Pose probe accepted a mismatched command.' >&2;exit 1;fi
rg -Fq 'pose probe action differs from recording' "$out/bad-action.log";[[ ! -e "$out/bad-action/result.json" ]]
cp "$out/original.jsonl" "$run/decisions.jsonl";printf '\001' | dd of="$run/actor-10.rgb" bs=1 seek=0 conv=notrunc status=none
if "$probe" "$out/policy" "$run" "$out/bad-rgb" > "$out/bad-rgb.log" 2>&1;then echo 'Pose probe accepted a changed image.' >&2;exit 1;fi
rg -Fq 'pose probe RGB differs from recorded frame hash' "$out/bad-rgb.log";[[ ! -e "$out/bad-rgb/result.json" ]]
echo 'Pose probe checks pre-action alignment and rejects mismatched commands or images.'
