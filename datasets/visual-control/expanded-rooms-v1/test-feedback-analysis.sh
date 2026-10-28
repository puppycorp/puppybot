#!/usr/bin/env bash
# Check offline feedback statistics and reject failed reconstructions.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mkdir -p "$out/policy/kernels" "$out/episode-parent/episode" "$out/episode-parent/verified"
printf 'weights\n' > "$out/policy/weights.bin";printf 'binary\n' > "$out/policy/policy";printf '{}\n' > "$out/policy/receipt.json";printf 'kernel\n' > "$out/policy/kernels/test"
printf '{}\n' > "$out/episode-parent/episode/initial.json";printf '{}\n' > "$out/episode-parent/episode/decisions.jsonl";printf '{}\n' > "$out/episode-parent/verified/result.json"
printf 'rgb\n' > "$out/episode-parent/episode/actor-1.rgb";printf 'feedback\n' > "$out/episode-parent/episode/actor-1.feedback"
cat > "$out/probe" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
sha="$(sha256sum "$1/weights.bin" | cut -d' ' -f1)";mkdir "$3";passed=true;if [[ "${PUPPYBOT_TEST_FAULT:-0}" == 1 ]];then passed=false;fi
jq -n --arg sha "$sha" --argjson passed "$passed" '{weightsSHA256:$sha,actualCommandsReplayedExactly:true,counterfactualDidNotAlterServerState:$passed,neutralFeedbackHypothetical:true,offlineCounterfactualOnly:true,simulatorPhaseUsedOnlyForAnalysis:true,rows:[{actualReturning:false,actualClass:0,neutralFeedbackClass:0,neutralFeedbackChangesAction:false},{actualReturning:true,actualClass:0,neutralFeedbackClass:0,neutralFeedbackChangesAction:false},{actualReturning:true,actualClass:3,neutralFeedbackClass:0,neutralFeedbackChangesAction:true},{actualReturning:true,actualClass:0,neutralFeedbackClass:3,neutralFeedbackChangesAction:true},{actualReturning:true,actualClass:3,neutralFeedbackClass:3,neutralFeedbackChangesAction:false}]}' > "$3/result.json"
EOF
chmod +x "$out/probe";driver="$project/datasets/visual-control/expanded-rooms-v1/analyze-feedback-sensitivity.sh"
bash "$driver" "$out/probe" "$out/policy" "$out/good" "$out/episode-parent/episode" > "$out/good.log" 2>&1
jq -e '.passed and .episodes==1 and .returnFrames==4 and .neutralFeedbackActionChanges==2 and .actualDriveReversals==3 and .neutralFeedbackDriveReversals==1 and .offlineCounterfactualOnly and .closedLoopBehaviorNotMeasured' "$out/good/summary.json" > /dev/null
if PUPPYBOT_TEST_FAULT=1 bash "$driver" "$out/probe" "$out/policy" "$out/bad" "$out/episode-parent/episode" > "$out/bad.log" 2>&1;then echo 'Failed feedback replay was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" != 0 && ! -e "$out/bad/summary.json" ]]
echo 'Offline feedback statistics and rejection checks passed.'
