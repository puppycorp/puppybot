#!/usr/bin/env bash
# Synthetic file-level audit test, including a deliberate duplicate.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="${1:?New output directory required}"
out="$(/usr/bin/realpath -m "$out")"
[[ ! -e "$out" ]]
mkdir -p "$out/corpus" "$out/pilot/packed" "$out/pilot/verified" "$out/pilot/runs" "$out/pilot/catalog"
truncate -s $((32+2*21224)) "$out/corpus/data.bin"
printf 'PVDATA04\002\000\000\000\000\000\000\000\001\000\000\000\000\000\000\000\001\000\000\000\000\000\000\000' | dd of="$out/corpus/data.bin" conv=notrunc status=none
for index in 0 1;do
    mkdir -p "$out/corpus/expert-$index/scene" "$out/pilot/catalog/$index" "$out/pilot/runs/expert-$index"
    printf 'corpus case %s\n' "$index" > "$out/corpus/expert-$index/scene/case.json"
    printf 'corpus environment %s\n' "$index" > "$out/corpus/expert-$index/scene/environment.bin"
    layout=49; role=true; if (( index ));then layout=149;role=false;fi
    /usr/bin/jq -n --argjson layout "$layout" --argjson role "$role" '{layoutId:$layout,fit:$role}' > "$out/pilot/catalog/$index/layout.json"
    printf 'pilot case %s\n' "$index" > "$out/pilot/catalog/$index/case.json"
    printf 'pilot environment %s\n' "$index" > "$out/pilot/catalog/$index/environment.bin"
    ln -s "$out/pilot/catalog/$index" "$out/pilot/runs/expert-$index/scene"
done
base="$out/mock-project/build/flex/sim/expanded-rooms-v1"
for layout in 18 19 20 21 22 23;do
    parent=generalization-benchmark-v1; if (( layout<20 ));then parent=unseen-benchmark-v2;fi
    for scene in {0..15};do
        dir="$base/$parent/scenes/$layout/$scene"; mkdir -p "$dir"
        printf 'evaluation case %s %s\n' "$layout" "$scene" > "$dir/case.json"
        printf 'evaluation environment %s\n' "$layout" > "$dir/environment.bin"
    done
done
printf 'synthetic pilot data\n' > "$out/pilot/packed/data.bin"
corpus_sha="$(/usr/bin/sha256sum "$out/corpus/data.bin" | /usr/bin/cut -d' ' -f1)"
pilot_sha="$(/usr/bin/sha256sum "$out/pilot/packed/data.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -n --arg sha "$corpus_sha" '{passed:true,episodes:2,fittingHistories:1,validationHistories:1,dataSHA256:$sha,newHistoriesIndependentlyAudited:true,existingDataBytePreserved:true,teacherLabelsTrainingOnly:true,actorInputsUnchanged:true}' > "$out/coverage.json"
/usr/bin/jq -n --arg sha "$pilot_sha" '{passed:true,episodes:2,dataSHA256:$sha,teacherLabelsTrainingOnly:true,actorTaskEventHint:false,studentAutonomousSuccessClaimed:false,automaticMerge:false}' > "$out/pilot/summary.json"
/usr/bin/jq -n --arg sha "$pilot_sha" '{passed:true,episodes:2,dataSHA256:$sha,studentRollinMaxAbsError:0,denseOracleLabels:true,taskEventHintAbsent:true}' > "$out/pilot/verified/result.json"
printf '0\n' > "$out/pilot/run.exit"
audit="$project/datasets/visual-control/expanded-rooms-v1/audit-gated-search-disjoint.sh"
PUPPYBOT_PROJECT="$out/mock-project" /usr/bin/bash "$audit" "$out/pilot" "$out/corpus" "$out/coverage.json" "$out/accepted" > "$out/accepted.log" 2>&1
/usr/bin/jq -e '.passed and .existingHistories==2 and .similarGeometryNotExcluded' "$out/accepted/result.json" > /dev/null
dev_audit="$project/datasets/visual-control/expanded-rooms-v1/audit-corpus-development.sh"
PUPPYBOT_PROJECT="$out/mock-project" /usr/bin/bash "$dev_audit" "$out/corpus" "$out/coverage.json" "$out/dev-accepted" > "$out/dev-accepted.log" 2>&1
/usr/bin/jq -e '.passed and .developmentCaseOverlap==0 and .developmentEnvironmentOverlap==0' "$out/dev-accepted/result.json" > /dev/null
cp "$out/corpus/expert-0/scene/case.json" "$base/unseen-benchmark-v2/scenes/18/0/case.json"
if PUPPYBOT_PROJECT="$out/mock-project" /usr/bin/bash "$dev_audit" "$out/corpus" "$out/coverage.json" "$out/dev-duplicate" > "$out/dev-duplicate.log" 2>&1;then echo 'Duplicate development case was accepted.' >&2;exit 1;fi
/usr/bin/jq -e '(.passed|not) and .developmentCaseOverlap==1' "$out/dev-duplicate/report.json" > /dev/null
[[ ! -e "$out/dev-duplicate/result.json" ]]
cp "$out/corpus/expert-0/scene/case.json" "$out/pilot/catalog/0/case.json"
if PUPPYBOT_PROJECT="$out/mock-project" /usr/bin/bash "$audit" "$out/pilot" "$out/corpus" "$out/coverage.json" "$out/duplicate" > "$out/duplicate.log" 2>&1;then echo 'Duplicate case was accepted.' >&2;exit 1;fi
[[ "$(< "$out/duplicate/run.exit")" == 1 && ! -e "$out/duplicate/result.json" ]]
echo 'Synthetic scene audit accepted disjoint cases and rejected a duplicate.'
