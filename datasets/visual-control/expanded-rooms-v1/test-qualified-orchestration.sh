#!/usr/bin/env bash
# Synthetic control-flow test: no real final scene or simulator is used.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
out="${1:?New output directory required}"
base="$project/build/flex/sim/expanded-rooms-v1"
original="$base/unseen-benchmark-v2/continued-202"
score="$base/unseen-benchmark-v2/score-continued-202.json"
policy="$base/matched-training-v3/expanded"
source="$project/datasets/visual-control/expanded-rooms-v1"
[[ ! -e "$out" ]]
mkdir -p "$out/cases/synthetic" "$out/resources/generalization" "$out/resources/final" "$out/no-candidate/selection"
printf '0\n' > "$out/no-candidate/run.exit"
printf '{"qualified":false,"reservedFinalStillRequired":true,"retainedPolicyOverwritten":false}\n' > "$out/no-candidate/selection/selection.json"
/usr/bin/jq '.candidate="synthetic" | .rows |= map(if .caseIndex<24 then .physicalReturned=true|.recordedPhysicalReturn=true|.found=true else .physicalReturned=false|.recordedPhysicalReturn=false end) | .physicalReturns=([.rows[]|select(.physicalReturned)]|length) | .openReturns=([.rows[]|select(.layoutId==18 and .physicalReturned)]|length) | .hiddenReturns=([.rows[]|select(.layoutId==19 and .physicalReturned)]|length) | .auditedApproaches=([.rows[]|select(.auditPassed and .found)]|length) | .meanSuccessfulSimulationSeconds=([.rows[]|select(.physicalReturned)|.simulationSeconds]|if length==0 then null else add/length end)' "$score" > "$out/cases/score-synthetic.json"
for i in {0..31};do
    dest="$out/cases/synthetic/$i"
    mkdir -p "$dest/verified" "$dest/$((9960000+i))"
    /usr/bin/jq --argjson index "$i" '.rows[]|select(.caseIndex==$index)' "$out/cases/score-synthetic.json" > "$dest/benchmark-row.json"
    /usr/bin/cp "$original/$i/verified/result.json" "$dest/verified/result.json"
    /usr/bin/jq -c '{state:{case:{passed:.recordedPhysicalReturn}}}' "$dest/benchmark-row.json" > "$dest/$((9960000+i))/decisions.jsonl"
done
cp "$source/select-episode-candidate.sh" "$out/resources/gate.sh"
/usr/bin/bash "$out/resources/gate.sh" "$out/qualified" "$out/cases/score-synthetic.json" "$policy" > /dev/null
/usr/bin/jq -e '.qualified and .selected.physicalReturns==24' "$out/qualified/selection.json" > /dev/null
mkdir "$out/qualified-wrapper"
cp -a "$out/qualified" "$out/qualified-wrapper/selection"
printf '0\n' > "$out/qualified-wrapper/run.exit"
cp -a "$base/generalization-benchmark-v1/scenes" "$base/generalization-benchmark-v1/policies" "$out/resources/generalization/"
cp -a "$base/final-benchmark-v1/policies" "$out/resources/final/"
cp "$source/final-report.jq" "$out/resources/final-report.jq"
cat > "$out/resources/audit.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$1"
printf '{"passed":true,"trainingHistories":236,"cases":16,"reservedFinalUntouched":true,"synthetic":true}\n' > "$1/result.json"
: > "$1/prior-shas.txt"
EOF
cat > "$out/resources/benchmark-generalization.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
count=6; [[ "$2" != selected ]] || count=13
/usr/bin/jq -n --arg name "$2" --argjson count "$count" '{candidate:$name,synthetic:true,episodes:16,completedRecordings:16,auditedEpisodes:16,auditFailures:0,physicalReturns:$count}' > "$PUPPYBOT_GENERALIZATION_OUTPUT/score-$2.json"
EOF
cat > "$out/resources/final/generate" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
root="$1"; [[ "$2" == 10 && "$3" == 12 && "$4" == validation ]]
mkdir "$root"
for layout in 10 11;do
  mkdir "$root/$layout"
  if [[ "$layout" == 10 ]];then rooms='[[0,0,2,2]]';x=1;else rooms='[[0,0,2,2],[3,0,5,2]]';x=4;fi
  /usr/bin/jq -n --argjson layout "$layout" --argjson rooms "$rooms" '{layoutId:$layout,fit:false,rooms:$rooms,synthetic:true}' > "$root/$layout/layout.json"
  printf 'synthetic environment %s\n' "$layout" > "$root/$layout/environment.bin"
  for scene in {0..7};do
    mkdir "$root/$layout/$scene"
    cp "$root/$layout/layout.json" "$root/$layout/environment.bin" "$root/$layout/$scene/"
    /usr/bin/jq -n --argjson x "$x" --argjson layout "$layout" --argjson scene "$scene" '{objects:[{position:[$x,1,0]}],synthetic:true,layout:$layout,scene:$scene}' > "$root/$layout/$scene/case.json"
  done
done
EOF
chmod +x "$out/resources/final/generate"
cat > "$out/resources/benchmark-final.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
count=6;open=3;hidden=3;seconds=100
if [[ "$2" == selected ]];then count=13;open=6;hidden=7;seconds=80;fi
if [[ "$2" == blackout ]];then count=4;open=2;hidden=2;seconds=110;fi
/usr/bin/jq -n --arg name "$2" --argjson count "$count" --argjson open "$open" --argjson hidden "$hidden" --argjson seconds "$seconds" '{candidate:$name,synthetic:true,episodes:16,completedRecordings:16,auditedEpisodes:16,auditFailures:0,physicalReturns:$count,openReturns:$open,hiddenReturns:$hidden,meanSuccessfulSimulationSeconds:$seconds}' > "$PUPPYBOT_FINAL_OUTPUT/score-$2.json"
EOF
files=()
while IFS= read -r -d '' file;do files+=("$file");done < <(find "$out/resources" -type f -print0 | sort -z)
/usr/bin/sha256sum "${files[@]}" > "$out/resources/inputs.sha256"
/usr/bin/bash "$source/evaluate-qualified.sh" "$out/result" "$out/resources" "$out/qualified-wrapper" "$out/no-candidate" > "$out/run.log" 2>&1
/usr/bin/jq -e '.qualified and .improvesBaseline and .blackoutHasFewerReturns and (.automaticPromotion|not) and .selected.synthetic and .blackout.synthetic' "$out/result/comparison.json" > /dev/null
/usr/bin/jq -e '.synthetic and .layoutId==10' "$out/result/final/scenes/10/layout.json" > /dev/null
cat > "$out/resources/corpus-audit.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$2" == "$PUPPYBOT_QUALIFIED_CORPUS_DIR" && "$3" == "$PUPPYBOT_QUALIFIED_COVERAGE" ]]
mkdir "$1"
/usr/bin/jq -n --arg data "$PUPPYBOT_TEST_DATA_SHA" '{passed:true,trainingDataSHA256:$data,cases:16,reservedFinalUntouched:true,synthetic:true}' > "$1/result.json"
: > "$1/prior-shas.txt"
EOF
/usr/bin/sha256sum "$out/resources/corpus-audit.sh" >> "$out/resources/inputs.sha256"
export PUPPYBOT_QUALIFIED_CORPUS_DIR="$out/synthetic-corpus" PUPPYBOT_QUALIFIED_COVERAGE="$out/synthetic-coverage"
export PUPPYBOT_TEST_DATA_SHA="$(/usr/bin/jq -r '.dataSHA256' "$policy/receipt.json")"
/usr/bin/bash "$source/evaluate-qualified.sh" "$out/corpus-result" "$out/resources" "$out/qualified-wrapper" "$out/no-candidate" > "$out/corpus-run.log" 2>&1
/usr/bin/jq -e '.qualified and .selected.synthetic' "$out/corpus-result/comparison.json" > /dev/null
export PUPPYBOT_TEST_DATA_SHA=incorrect
if /usr/bin/bash "$source/evaluate-qualified.sh" "$out/bad-corpus-result" "$out/resources" "$out/qualified-wrapper" "$out/no-candidate" > "$out/bad-corpus-run.log" 2>&1;then
    echo 'A corpus audit for different training data was accepted.' >&2;exit 1
fi
[[ "$(< "$out/bad-corpus-result/run.exit")" == 1 && ! -e "$out/bad-corpus-result/generalization" && ! -e "$out/bad-corpus-result/final" ]]
unset PUPPYBOT_QUALIFIED_CORPUS_DIR PUPPYBOT_QUALIFIED_COVERAGE
printf '%s\n' '! /usr/bin/rg -Fxq "$hash" "$prior"' >> "$out/resources/audit.sh"
/usr/bin/awk -v path="$out/resources/audit.sh" '$2!=path' "$out/resources/inputs.sha256" > "$out/resources/inputs.tmp"
/usr/bin/mv "$out/resources/inputs.tmp" "$out/resources/inputs.sha256"
/usr/bin/sha256sum "$out/resources/audit.sh" >> "$out/resources/inputs.sha256"
if /usr/bin/bash "$source/evaluate-qualified.sh" "$out/unsafe-result" "$out/resources" "$out/qualified-wrapper" "$out/no-candidate" > "$out/unsafe-run.log" 2>&1;then
    echo 'An unsafe frozen overlap audit was accepted.' >&2;exit 1
fi
[[ "$(< "$out/unsafe-result/run.exit")" == 1 && ! -e "$out/unsafe-result/generalization" && ! -e "$out/unsafe-result/final" ]]
/usr/bin/rg -q 'unsafe overlap check' "$out/unsafe-run.log"
echo 'Synthetic qualified-candidate orchestration passed; no real reserved scene was generated.'
