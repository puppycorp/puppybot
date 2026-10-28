#!/usr/bin/env bash
set -euo pipefail

out="${1:?New output directory is required}"
shift
[[ ! -e "$out" && $# -ge 2 && $(($#%2)) == 0 ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
index=0
while (( $# ));do
    score="$1";policy="$2";shift 2
    sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
    binary_sha="$(/usr/bin/sha256sum "$policy/policy" | /usr/bin/cut -d' ' -f1)"
    score_sha="$(/usr/bin/sha256sum "$score" | /usr/bin/cut -d' ' -f1)"
    /usr/bin/jq -e --arg sha "$sha" --arg binary "$binary_sha" '.weightsSHA256==$sha and .binarySHA256==$binary and .taskFeedback==false' "$policy/receipt.json" > /dev/null
    /usr/bin/jq -e --arg sha "$sha" '
        .episodes==32 and (.rows|length)==32 and ([.rows[].caseIndex]|sort)==[range(0;32)] and
        all(.rows[]; .layoutId==(18+(.caseIndex/16|floor)) and .sceneId==(.caseIndex%16) and .policyWeightsSHA256==$sha and
            (.physicalReturned==(.recordingCompleted and .auditPassed and .recordedPhysicalReturn)) and
            ((.physicalReturned|not) or .found) and ((.auditPassed|not) or .recordingCompleted) and
            ((.recordingCompleted|not) or (.seed==(9960000+.caseIndex) and .maximumBrickDistanceM==0.35 and .suppliedMap==false and .taskEventHint==false))) and
        .completedRecordings==([.rows[]|select(.recordingCompleted)]|length) and
        .auditedEpisodes==([.rows[]|select(.auditPassed)]|length) and
        .auditFailures==([.rows[]|select(.auditPassed|not)]|length) and
        .physicalReturns==([.rows[]|select(.physicalReturned)]|length) and
        .auditedApproaches==([.rows[]|select(.auditPassed and .found)]|length) and
        .openReturns==([.rows[]|select(.layoutId==18 and .physicalReturned)]|length) and
        .hiddenReturns==([.rows[]|select(.layoutId==19 and .physicalReturned)]|length) and
        (([.rows[]|select(.physicalReturned)|.simulationSeconds]|if length==0 then null else add/length end) as $mean |
            (($mean==null and .meanSuccessfulSimulationSeconds==null) or ($mean!=null and ((.meanSuccessfulSimulationSeconds-$mean)|fabs)<0.000001)))' "$score" > /dev/null
    candidate="$(/usr/bin/jq -r '.candidate' "$score")"
    [[ "$candidate" =~ ^[a-zA-Z0-9_-]+$ ]]
    root="$(/usr/bin/dirname "$score")/$candidate"
    for case_index in {0..31};do
        row="$root/$case_index/benchmark-row.json"
        /usr/bin/jq -e --argjson index "$case_index" --slurpfile row "$row" '[.rows[]|select(.caseIndex==$index)]==[$row[0]]' "$score" > /dev/null
        if /usr/bin/jq -e '.auditPassed' "$row" > /dev/null;then
            /usr/bin/jq -e --arg sha "$sha" '.passed and .weightsSHA256==$sha and .commandReplayMaxAbsError==0 and .taskEventHintAbsent and .blackout==false' "$root/$case_index/verified/result.json" > /dev/null
        fi
        if /usr/bin/jq -e '.recordingCompleted' "$row" > /dev/null;then
            expected="$(/usr/bin/jq -r '.recordedPhysicalReturn' "$row")"
            /usr/bin/tail -n 1 "$root/$case_index/$((9960000+case_index))/decisions.jsonl" | /usr/bin/jq -e --argjson expected "$expected" '.state.case.passed==$expected' > /dev/null
        fi
    done
    [[ "$(/usr/bin/sha256sum "$score" | /usr/bin/cut -d' ' -f1)" == "$score_sha" ]]
    /usr/bin/jq --arg policy "$policy" --arg score "$score" --arg weights "$sha" --arg scoreSHA "$score_sha" '.+{policyDirectory:$policy,scoreFile:$score,weightsSHA256:$weights,scoreSHA256:$scoreSHA}' "$score" > "$out/candidate-$index.json"
    index=$((index+1))
done
/usr/bin/jq -s 'if ([.[].candidate]|unique|length)!=length then error("duplicate candidate names") else map(select(.episodes==32 and .completedRecordings==32 and .auditedEpisodes==32 and .auditFailures==0 and .physicalReturns>=24 and .openReturns>=8 and .hiddenReturns>=8))|sort_by([(-.physicalReturns),.meanSuccessfulSimulationSeconds,.candidate])|{qualified:(length>0),selected:.[0],qualifyingCandidates:length,thresholds:{returns:24,openReturns:8,hiddenReturns:8},reservedFinalStillRequired:true,retainedPolicyOverwritten:false} end' "$out"/candidate-*.json > "$out/selection.json"
echo 'Candidate gate evaluated; qualifying still requires separate generalization and final tests.'
