#!/usr/bin/env bash
# Synthetic distance-analysis test; no simulator is run.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(/usr/bin/realpath -m "${1:?New output directory required}")"
[[ ! -e "$out" ]]
pair="$out/pair"
mkdir -p "$pair/baseline-policy" "$pair/augmented-policy"
printf '0\n' > "$pair/run.exit"
printf '{"exploratory":true,"episodesPerModel":4,"optimizerStepsPerModel":98,"initialWeightsIdentical":true,"reservedFinalStillRequired":true,"automaticPromotion":false}\n' > "$pair/comparison.json"
for arm in baseline augmented;do
    printf '%s weights\n' "$arm" > "$pair/$arm-policy/weights.bin"
    sha="$(/usr/bin/sha256sum "$pair/$arm-policy/weights.bin" | /usr/bin/cut -d' ' -f1)"
    for index in 2 15 16 17;do
        seed=$((9960000+index));root="$pair/$arm-screen/$index";episode="$root/$seed"
        mkdir -p "$episode/scene" "$root/verified"
        printf '{}\n' > "$episode/initial.json"
        printf '{"action":[0,1]}\n{"action":[0,-1]}\n' > "$episode/decisions.jsonl"
        for file in case.json environment.bin;do printf 'scene %s %s\n' "$index" "$file" > "$episode/scene/$file";done
        /usr/bin/jq -n --arg sha "$sha" '{passed:true,weightsSHA256:$sha,commandReplayMaxAbsError:0,taskEventHintAbsent:true,blackout:false}' > "$root/verified/result.json"
        /usr/bin/jq -n --arg sha "$sha" '{complete:true,episodes:1,rows:[{policyWeightsSHA256:$sha,suppliedMap:false,taskEventHint:false,found:false,success:false}]}' > "$root/summary.json"
    done
done
cat > "$out/measure" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mkdir "$2";distance=0.5;if [[ "$1" == */baseline-screen/* ]];then distance=1;fi
/usr/bin/jq -n --argjson d "$distance" '{closestPlanarBaseToBrickM:$d,synthetic:true}' > "$2/result.json"
EOF
chmod +x "$out/measure"
driver="$project/datasets/visual-control/expanded-rooms-v1/analyze-gated-search-screen.sh"
PUPPYBOT_PROJECT="$project" /usr/bin/bash "$driver" "$pair" "$out/good" "$out/measure" > "$out/good.log" 2>&1
/usr/bin/jq -e '.baselineMeanClosestM==1 and .augmentedMeanClosestM==0.5 and (.rows|length)==8 and all(.rows[]; .motion.actions==2 and .motion.forward==1 and .motion.reverse==1)' "$out/good/comparison.json" > /dev/null
/usr/bin/jq '.passed=false' "$pair/baseline-screen/2/verified/result.json" > "$pair/baseline-screen/2/verified/tmp.json"
mv "$pair/baseline-screen/2/verified/tmp.json" "$pair/baseline-screen/2/verified/result.json"
if PUPPYBOT_PROJECT="$project" /usr/bin/bash "$driver" "$pair" "$out/bad" "$out/measure" > "$out/bad.log" 2>&1;then echo 'An unaudited recording was accepted.' >&2;exit 1;fi
[[ "$(< "$out/bad/run.exit")" == 1 && ! -e "$out/bad/comparison.json" ]]
echo 'Screen distance analysis checks motion counts and rejects failed replay audits.'
