#!/usr/bin/env bash
# Synthetic wiring test only: the stub is not a simulator or task evaluation.
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
output="${1:?New output directory required}"
mkdir "$output"
output="$(cd "$output" && pwd)"
for kind in general final; do
    root="$output/$kind"
    mkdir -p "$root/native-path" "$root/runtime/build/flex/control" "$root/scenes"
    ln -s /usr/bin/mkdir "$root/native-path/mkdir"
    for layout in 20 21 22 23; do
        [[ "$kind" == general ]] || continue
        for scene in 0 5 10 15; do mkdir -p "$root/scenes/$layout/$scene"; printf 'case-%s-%s\n' "$layout" "$scene" > "$root/scenes/$layout/$scene/case.json"; printf 'env-%s\n' "$layout" > "$root/scenes/$layout/$scene/environment.bin"; done
    done
    for layout in 10 11; do
        [[ "$kind" == final ]] || continue
        for scene in {0..7}; do mkdir -p "$root/scenes/$layout/$scene"; printf 'case-%s-%s\n' "$layout" "$scene" > "$root/scenes/$layout/$scene/case.json"; printf 'env-%s\n' "$layout" > "$root/scenes/$layout/$scene/environment.bin"; done
    done
    cat > "$root/runtime/build/flex/control/control" <<'EOF'
#!/bin/bash
set -euo pipefail
command="$1"; shift
if [[ "$command" == help ]]; then if [[ -f legacy-only ]]; then printf 'legacy only\n'; else printf '%s\n' '--large-model'; fi; exit 0; fi
policy= scene= output= seed= large=false blackout=false
while (( $# )); do
    case "$1" in
        --policy) policy="$2"; shift 2;; --scene) scene="$2"; shift 2;; --output) output="$2"; shift 2;; --seed) seed="$2"; shift 2;;
        --run|--episodes|--horizon) shift 2;; --large-model) large=true; shift;; --blackout) blackout=true; shift;; --hidden-target) shift;; *) exit 2;;
    esac
done
width="$(/usr/bin/jq -r '.memoryWidth // 128' "$policy/receipt.json")"
if [[ "$width" == 256 ]]; then [[ "$large" == true ]]; else [[ "$width" == 128 && "$large" == false ]]; fi
sha="$(/usr/bin/sha256sum "$policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
if [[ "$command" == run ]]; then
    /usr/bin/mkdir -p "$output/$seed/scene" "$output/policy"
    /usr/bin/cp "$scene/case.json" "$scene/environment.bin" "$output/$seed/scene/"
    /usr/bin/cp "$policy/weights.bin" "$policy/receipt.json" "$output/policy/"
    /usr/bin/jq -n --argjson seed "$seed" --arg sha "$sha" --argjson blackout "$blackout" --argjson large "$large" '{complete:true,episodes:1,rows:[{seed:$seed,found:false,success:false,simulationSeconds:60,policyWeightsSHA256:$sha,blackout:$blackout,maximumBrickDistanceM:0.35,suppliedMap:false,taskEventHint:false,testLargeFlag:$large}]}' > "$output/summary.json"
    printf '{"state":{"case":{"passed":false}}}\n' > "$output/$seed/decisions.jsonl"
elif [[ "$command" == verify ]]; then
    /usr/bin/mkdir -p "$output"
    /usr/bin/jq -n --arg sha "$sha" --argjson blackout "$blackout" --argjson large "$large" '{passed:true,weightsSHA256:$sha,commandReplayMaxAbsError:0,blackout:$blackout,testLargeFlag:$large}' > "$output/result.json"
else exit 2; fi
EOF
    chmod +x "$root/runtime/build/flex/control/control"
done
for width in 128 256; do
    policy="$output/policy-$width"; mkdir "$policy"; printf 'weights-%s\n' "$width" > "$policy/weights.bin"
    jq -n --argjson width "$width" '{memoryWidth:$width}' > "$policy/receipt.json"
    PUPPYBOT_PROJECT="$project" PUPPYBOT_GENERALIZATION_OUTPUT="$output/general" bash "$project/datasets/visual-control/expanded-rooms-v1/benchmark-generalization.sh" "$policy" "width-$width" > "$output/general-$width.log" 2>&1
    jq -e --argjson large "$([[ "$width" == 256 ]] && echo true || echo false)" '.episodes==16 and .auditedEpisodes==16 and all(.rows[];.testLargeFlag==$large)' "$output/general/score-width-$width.json" > /dev/null
    for blackout in false true; do
        PUPPYBOT_PROJECT="$project" PUPPYBOT_FINAL_OUTPUT="$output/final" bash "$project/datasets/visual-control/expanded-rooms-v1/benchmark-final.sh" "$policy" "width-$width-$blackout" "$blackout" > "$output/final-$width-$blackout.log" 2>&1
        jq -e --argjson large "$([[ "$width" == 256 ]] && echo true || echo false)" --argjson blackout "$blackout" '.episodes==16 and .auditedEpisodes==16 and all(.rows[];.testLargeFlag==$large and .blackout==$blackout)' "$output/final/score-width-$width-$blackout.json" > /dev/null
    done
done
touch "$output/general/runtime/legacy-only"
if PUPPYBOT_PROJECT="$project" PUPPYBOT_GENERALIZATION_OUTPUT="$output/general" bash "$project/datasets/visual-control/expanded-rooms-v1/benchmark-generalization.sh" "$output/policy-256" rejected > "$output/rejected.log" 2>&1; then echo 'Legacy runtime accepted a 256-value model.' >&2; exit 1; fi
[[ ! -e "$output/general/rejected" ]]
echo 'Synthetic benchmark wiring supports both memory widths and blackout; legacy runtimes reject large models.'
