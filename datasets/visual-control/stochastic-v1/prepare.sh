#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/stochastic-v1"
dataset="$project/datasets/visual-control/stochastic-v1"
original="$project/build/flex/sim/forward-contact-v2/policy-contact142-20"
[[ ! -e "$root/prepared.exit" && ! -e "$root/policy-greedy" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/prepared.exit"' EXIT
cd "$project"
[[ "$(/usr/bin/sha256sum "$original/weights.bin" | /usr/bin/cut -d' ' -f1)" == c38fa6cbc57c7a1da996f2c50fa3b2deb251c71c073698ce1269a3e833183ab7 ]]
mkdir "$root/recipes" "$root/models"
cp "$dataset/"* "$root/recipes/"
cp -a build/flex/sim/start-pose-v1/models/native-path "$root/models/native-path"
cp -a datasets/visual-control/approach35-v1/artifacts/runtime "$root/runtime"
cp build/flex/control/forward-tests "$root/forward-tests"
build/flex/control/compiler "$dataset/tests.flex" -o "$root/tests"
"$root/tests" "$root/tests-final.json"
for arm in greedy half one; do
    build/flex/control/compiler "$dataset/$arm.flex" -o "$root/$arm"
    cp -a "$original" "$root/policy-$arm"
    cp "$root/$arm" "$root/policy-$arm/policy"
    sha="$(/usr/bin/sha256sum "$root/policy-$arm/policy" | /usr/bin/cut -d' ' -f1)"
    temperature=0;if [[ "$arm" == half ]];then temperature=0.5;elif [[ "$arm" == one ]];then temperature=1;fi
    /usr/bin/jq --arg sha "$sha" --arg arm "$arm" --argjson temperature "$temperature" '.binarySHA256=$sha|.method=("Fixed-weight joint-action decoder comparison: "+$arm)|.actionSampling={temperature:$temperature,seed:73,reset:"zero recurrent state",source:"network logits only"}' "$original/receipt.json" > "$root/policy-$arm/receipt.json"
    /usr/bin/cmp "$root/policy-$arm/weights.bin" "$original/weights.bin"
done
/usr/bin/find "$root/runtime" -type f -print0 | /usr/bin/sort -z | /usr/bin/xargs -0 /usr/bin/sha256sum > "$root/runtime.sha256"
/usr/bin/sha256sum "$root/recipes/"* "$root/"{greedy,half,one,forward-tests,tests} > "$root/recipes.sha256"
echo 'Fixed-weight decoder variants prepared; native conformance and autonomous evaluation remain required.'
