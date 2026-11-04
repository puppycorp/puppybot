#!/usr/bin/env bash
# Run a single preselected policy and the exploring teacher on a reserved
# virtual-fetch catalog. This is NOT a policy-selection tool or physical
# manipulation test. Every input is registered before the first game.
# Usage: evaluate-heldout.sh CATALOG MODEL SELECTION_RECEIPT NEW_OUTPUT
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
[[ $# == 4 ]] || { echo 'Expected CATALOG MODEL SELECTION_RECEIPT NEW_OUTPUT' >&2; exit 1; }
# A receipt containing self-asserted booleans is not sufficient evidence of
# candidate qualification. Keep this runner disabled until an independent
# selection verifier checks and binds every required artifact. The code below
# is a protocol scaffold and must not be enabled merely by creating a receipt.
echo 'Held-out runner disabled: an independent selection-artifact verifier is not yet implemented.' >&2
exit 1
catalog=$(realpath -e "$1"); model=$(realpath -e "$2"); selection=$(realpath -e "$3"); output=$(realpath -m "$4")
[[ ! -e "$output" && -f "$catalog/manifest.json" && -f "$model/receipt.json" && -f "$selection" ]] || { echo 'Missing input or output already exists' >&2; exit 1; }
cd "$project"
S=$project/datasets/visual-control/chase-v1/levels
weights=$(sha256sum "$model/weights.bin" | cut -d' ' -f1)
jq -e --arg weights "$weights" '.selectedWeightsSHA256 == $weights and .selectionOnly == true and .allLevelsAudited == true and .standardFetchAudited == true and .heldoutUsed == false' "$selection" > /dev/null || { echo 'Candidate lacks a complete selection-only receipt; do not use holdout for tuning' >&2; exit 1; }
jq -e '.status == "reserved_not_evaluated" and .task == "virtual-fetch" and .gamesPerLevel == 32 and .actionsPerGame == 300 and .teacher == "explore-teacher" and .cameraPitchDegrees == 82 and (.rows | length) == 160' "$catalog/manifest.json" > /dev/null
mkdir -p "$(dirname "$output")"; mkdir "$output"
trap 'status=$?; printf "%s\n" "$status" > "$output/run.exit"' EXIT
files=("$catalog/manifest.json" "$model/receipt.json" "$model/weights.bin" "$model/policy" "$selection"
       "$S/evaluate-heldout.sh" "$S/audit-heldout.py" "$S/audit-selection.py" "$S/goal-report.py"
       "$project/build/flex/control/control" "$project/build/flex/control/simulator" "$project/build/flex/rocm-runtime/libamdhip64.so")
while IFS= read -r -d '' file; do files+=("$file"); done < <(find "$model/kernels" -type f -print0 | sort -z)
[[ -d "$model/kernels" && ${#files[@]} -gt 11 ]] || { echo 'Missing policy kernels' >&2; exit 1; }
for ((level=1;level<=5;level++)); do
    leveldir="$output/L$level"; mkdir -p "$leveldir/catalogs"
    for ((part=0;part<4;part++)); do
        mkdir "$leveldir/catalogs/$part"
        for ((index=0;index<8;index++)); do
            game=$((part*8+index)); expected=$((1700000000+level*100+game))
            row=$(jq -ce --argjson level "$level" --argjson game "$game" --argjson seed "$expected" '[.rows[] | select(.level == $level and .index == $game and .seed == $seed)] | if length == 1 then .[0] else error("bad catalog row") end' "$catalog/manifest.json")
            relative=$(jq -r '.scene' <<< "$row"); scene=$(realpath -e "$catalog/$relative")
            [[ "$scene" == "$catalog/"* ]] || { echo 'Scene escapes catalog' >&2; exit 1; }
            for entry in 'case.json caseSHA256' 'environment.bin environmentSHA256' 'layout.json layoutSHA256'; do
                read -r name key <<< "$entry"; expected_sha=$(jq -r --arg key "$key" '.[$key]' <<< "$row")
                [[ $(sha256sum "$scene/$name" | cut -d' ' -f1) == "$expected_sha" ]] || { echo "Changed scene: $scene/$name" >&2; exit 1; }
                files+=("$scene/$name")
            done
            ln -s "$scene" "$leveldir/catalogs/$part/$index"
        done
    done
done
sha256sum "${files[@]}" > "$output/inputs.sha256"
sha256sum -c "$output/inputs.sha256" > /dev/null
jq -n --arg catalog "$(sha256sum "$catalog/manifest.json" | cut -d' ' -f1)" --arg inputs "$(sha256sum "$output/inputs.sha256" | cut -d' ' -f1)" --arg weights "$weights" '{catalogSHA256:$catalog,inputsSHA256:$inputs,candidateWeightsSHA256:$weights,registeredBeforePlay:true}' > "$output/registration.json"
for ((level=1;level<=5;level++)); do
    leveldir="$output/L$level"
    for kind in teacher candidate; do
        sha256sum -c "$output/inputs.sha256" > /dev/null
        mkdir "$leveldir/$kind"; pids=()
        for ((part=0;part<4;part++)); do
            seed=$((1700000000+level*100+part*8)); out="$leveldir/$kind/$part"
            common=(--chase --scene-catalog "$leveldir/catalogs/$part" --output "$out" --episodes 8 --horizon 300 --seed "$seed" --lean --wheel-odometry --fetch --level "$level" --camera-pitch 82)
            if [[ $kind == teacher ]]; then
                env -u WAYLAND_DISPLAY -u DISPLAY SDL_VIDEODRIVER=offscreen nice -n 19 "$project/build/flex/control/control" collect "${common[@]}" --validation 1 --explore-teacher > "$leveldir/$kind/$part.log" 2>&1 &
            else
                env -u WAYLAND_DISPLAY -u DISPLAY SDL_VIDEODRIVER=offscreen nice -n 19 "$project/build/flex/control/control" run --policy "$model" "${common[@]}" > "$leveldir/$kind/$part.log" 2>&1 &
            fi
            pids+=("$!")
        done
        status=0; for pid in "${pids[@]}"; do wait "$pid" || status=1; done
        (( status == 0 )) || { echo "Failed $kind level $level; partial results retained" >&2; exit 1; }
    done
done
sha256sum -c "$output/inputs.sha256" > /dev/null
python3 -I "$S/audit-heldout.py" "$catalog" "$model" "$output" > "$output/report.json.tmp"
mv "$output/report.json.tmp" "$output/report.json"
cat "$output/report.json"
