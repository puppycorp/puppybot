#!/usr/bin/env bash
# A long preparation must reject a mismatched preparer before processing data.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1";admission="$root/incomplete-return-admission-v1";source="$root/memory-pose-354-source-v2";preflight="$root/memory-pose-354-preflight-v2/preflight.json"
mkdir -p "$admission/expanded" "$source" "$(dirname "$preflight")";printf '0\n' > "$admission/run.exit";printf 'dataset\n' > "$admission/expanded/data.bin";printf '{}\n' > "$admission/expanded/report.json"
sha="$(sha256sum "$admission/expanded/data.bin" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,episodes:354,fittingHistories:240,validationHistories:114,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,existingDataBytePreserved:true,actorInputsUnchanged:true,incompleteEpisodesClaimedSuccessful:false}' > "$admission/coverage.json"
cat > "$source/prepare-memory-pose" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$3";printf 'targets\n' > "$3/targets.bin";sha="$(sha256sum "$1" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,verifiedAgainstPhysicalTrace:true,sourceFilesStableDuringVerification:true,actorInputsUnchanged:true,preActionRGBAndFeedbackMatched:true,inverseTransformChecked:true,normalizationMetres:8,episodes:354,fittingHistories:240,validationHistories:114,sourceDataSHA256:$sha}' > "$3/receipt.json"
EOF
printf '#!/usr/bin/env bash\nexit 0\n' > "$source/pose-open-tests";chmod +x "$source/prepare-memory-pose" "$source/pose-open-tests"
sha="$(sha256sum "$source/prepare-memory-pose" | cut -d' ' -f1)"
jq -n --arg sha "$sha" '{passed:true,preparerSHA256:$sha,physicalTraceChecked:true,preActionRGBAndFeedbackMatched:true,inverseTransformChecked:true,poseAndImageTamperingRejected:true,progressChecked:true}' > "$preflight"
driver="$project/datasets/visual-control/expanded-rooms-v1/prepare-memory-pose-354.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_MEMORY_POSE_OUT="$out/good" bash "$driver" > "$out/good.log" 2>&1
[[ "$(< "$out/good/run.exit")" == 0 && -f "$out/good/targets/receipt.json" ]]
jq '.preparerSHA256="wrong"' "$preflight" > "$out/bad-preflight.json";cp "$out/bad-preflight.json" "$preflight"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_MEMORY_POSE_OUT="$out/bad" bash "$driver" > "$out/bad.log" 2>&1;then echo 'Preparation accepted an unverified executable.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" != 0 && ! -e "$out/bad/targets" ]]
echo 'Pose preparation rejects an unverified executable before the long pass.'
