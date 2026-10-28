#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
baseline="${PUPPYBOT_COMPARE_BASELINE:-$root/return-benchmark-v1}"
candidate="${PUPPYBOT_COMPARE_CANDIDATE:-$root/return-cohort-benchmark-v2}"
out="${PUPPYBOT_COMPARE_OUTPUT:-$root/return-cohort-comparison-v2}"
candidate_steps="${PUPPYBOT_COMPARE_CANDIDATE_STEPS:-980}"
candidate_training="${PUPPYBOT_COMPARE_CANDIDATE_TRAINING:-$root/return-cohort-training-v2}"
baseline_training="${PUPPYBOT_COMPARE_BASELINE_TRAINING:-$root/return-training-v1}"
baseline_steps="${PUPPYBOT_COMPARE_BASELINE_STEPS:-960}"
baseline_histories="${PUPPYBOT_COMPARE_BASELINE_HISTORIES:-256}"
candidate_histories="${PUPPYBOT_COMPARE_CANDIDATE_HISTORIES:-264}"
require_equal_updates="${PUPPYBOT_COMPARE_REQUIRE_EQUAL_UPDATES:-0}"
[[ "$require_equal_updates" == 0 || "$require_equal_updates" == 1 ]]
for number in "$baseline_steps" "$candidate_steps" "$baseline_histories" "$candidate_histories"; do [[ "$number" =~ ^[1-9][0-9]*$ && "$number" -le 100000000 ]]; done
[[ ! -e "$out" ]]
/usr/bin/mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
trap 'exit 143' TERM
printf '%s\n' "$BASHPID" > "$out/run.pid"
for job in "$baseline/run" "$candidate/run"; do
    while [[ ! -f "$job.exit" ]]; do
        [[ -f "$job.pid" ]] && kill -0 "$(< "$job.pid")" || { echo "$job ended without a status." >&2; exit 1; }
        /usr/bin/sleep 20
    done
    [[ "$(< "$job.exit")" == 0 ]] || { echo "$job failed; comparison not published." >&2; exit 1; }
done
baseline_policy="$baseline_training/policy"
candidate_policy="$candidate_training/policy"
for policy in "$baseline_policy" "$candidate_policy"; do
    /usr/bin/jq -e '.epochs==10 and .batch==2 and .learningRateMicros==100 and .seed==197 and .memoryWidth==256 and .sequenceMirrorAugmentation and .heatmapActorFeatures and .heatmapActorGradientDetached and .cameraEventAuxiliary and (.taskFeedback|not)' "$policy/receipt.json" > /dev/null
done
[[ "$(/usr/bin/jq -r .initialWeightsSHA256 "$baseline_policy/receipt.json")" == "$(/usr/bin/jq -r .initialWeightsSHA256 "$candidate_policy/receipt.json")" ]]
if [[ "$baseline_histories" == "$candidate_histories" ]]; then
    for field in dataSHA256 targetPositionTargetsSHA256; do
        left="$(/usr/bin/jq -r --arg field "$field" '.[$field]' "$baseline_policy/receipt.json")"
        right="$(/usr/bin/jq -r --arg field "$field" '.[$field]' "$candidate_policy/receipt.json")"
        [[ "$left" != null && "$left" == "$right" ]]
    done
fi
/usr/bin/jq -se --argjson steps "$baseline_steps" 'last | .optimizerSteps==$steps' "$baseline_policy/curves.jsonl" > /dev/null
/usr/bin/jq -se --argjson steps "$candidate_steps" 'last | .optimizerSteps==$steps' "$candidate_policy/curves.jsonl" > /dev/null
baseline_penalty="$(/usr/bin/jq -r '.reversalPenaltyMilli // 0' "$baseline_policy/receipt.json")"
candidate_penalty="$(/usr/bin/jq -r '.reversalPenaltyMilli // 0' "$candidate_policy/receipt.json")"
for number in "$baseline_penalty" "$candidate_penalty"; do [[ "$number" =~ ^[0-9]+$ && "$number" -le 10000 ]]; done
baseline_gate="$(/usr/bin/jq -r '.phaseGatedNavigation' "$baseline_policy/receipt.json")"
candidate_gate="$(/usr/bin/jq -r '.phaseGatedNavigation' "$candidate_policy/receipt.json")"
for value in "$baseline_gate" "$candidate_gate"; do [[ "$value" == true || "$value" == false ]]; done
if [[ "$baseline_histories" != "$candidate_histories" ]]; then [[ "$baseline_penalty" == "$candidate_penalty" ]]; fi
if [[ "$baseline_histories" != "$candidate_histories" || "$baseline_penalty" != "$candidate_penalty" ]]; then [[ "$baseline_gate" == "$candidate_gate" ]]; fi
if [[ "$require_equal_updates" == 1 ]]; then [[ "$baseline_steps" == "$candidate_steps" ]]; fi
for pair in "$baseline:$baseline_policy" "$candidate:$candidate_policy"; do
    score="${pair%%:*}"; policy="${pair#*:}"; sha="$(/usr/bin/jq -r .weightsSHA256 "$policy/receipt.json")"
    /usr/bin/jq -e --arg sha "$sha" 'all(.rows[]; .policyWeightsSHA256==$sha)' "$score/score.json" > /dev/null
done
for score in "$baseline/score.json" "$candidate/score.json"; do
    /usr/bin/jq -e '.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32 and ([.rows[].caseIndex]|sort)==[range(0;32)] and all(.rows[]; .recordingCompleted and .auditPassed and (.suppliedMap|not) and (.taskEventHint|not) and .maximumBrickDistanceM==0.35)' "$score" > /dev/null
done
/usr/bin/sha256sum "$baseline/score.json" "$candidate/score.json" "$baseline_policy/receipt.json" "$baseline_policy/curves.jsonl" "$candidate_policy/receipt.json" "$candidate_policy/curves.jsonl" > "$out/inputs.sha256"
/usr/bin/jq -n --argjson baselineSteps "$baseline_steps" --argjson candidateSteps "$candidate_steps" --argjson baselineHistories "$baseline_histories" --argjson candidateHistories "$candidate_histories" --argjson baselinePenalty "$baseline_penalty" --argjson candidatePenalty "$candidate_penalty" --argjson baselineGate "$baseline_gate" --argjson candidateGate "$candidate_gate" --slurpfile baseline "$baseline/score.json" --slurpfile candidate "$candidate/score.json" '
    [$candidate[0].rows[] as $c | $baseline[0].rows[] | select(.caseIndex==$c.caseIndex) |
        {caseIndex,layoutId,seed,baselineApproach:.found,candidateApproach:$c.found,
         baselineReturn:.physicalReturned,candidateReturn:$c.physicalReturned,
         matchingCase:(.layoutId==$c.layoutId and .seed==$c.seed)}] as $pairs |
    {complete:true,developmentOnly:true,identicalCases:($pairs|length==32 and all(.[];.matchingCase)),
     baseline:{histories:$baselineHistories,optimizerSteps:$baselineSteps,reversalPenaltyMilli:$baselinePenalty,phaseGated:$baselineGate,approaches:$baseline[0].approaches,returns:$baseline[0].returns,openReturns:$baseline[0].openReturns,hiddenReturns:$baseline[0].hiddenReturns,meanSuccessfulSimulationSeconds:$baseline[0].meanSuccessfulSimulationSeconds},
     candidate:{histories:$candidateHistories,optimizerSteps:$candidateSteps,reversalPenaltyMilli:$candidatePenalty,phaseGated:$candidateGate,approaches:$candidate[0].approaches,returns:$candidate[0].returns,openReturns:$candidate[0].openReturns,hiddenReturns:$candidate[0].hiddenReturns,meanSuccessfulSimulationSeconds:$candidate[0].meanSuccessfulSimulationSeconds},
     gainedApproaches:($pairs|map(select((.baselineApproach|not) and .candidateApproach))|length),
     lostApproaches:($pairs|map(select(.baselineApproach and (.candidateApproach|not)))|length),
     gainedReturns:($pairs|map(select((.baselineReturn|not) and .candidateReturn))|length),
     lostReturns:($pairs|map(select(.baselineReturn and (.candidateReturn|not)))|length),
     reservedFinalStillRequired:true,automaticPromotion:false,rows:$pairs}' > "$out/comparison.json"
/usr/bin/jq -e '.complete and .identicalCases and (.rows|length)==32' "$out/comparison.json" > /dev/null
/usr/bin/sha256sum -c "$out/inputs.sha256" > "$out/integrity-after.log"
