#!/usr/bin/env bash
set -euo pipefail

corpus="${1:?Corpus directory is required}"
out="${2:?New output directory is required}"
[[ ! -e "$out" ]]
mkdir "$out"
trap 'status=$?; printf "%s\n" "$status" > "$out/run.exit"' EXIT
read -r episodes fit length < <(/usr/bin/od -An -tu8 -w24 -j8 -N24 "$corpus/data.bin")
[[ "$episodes" -ge 2 && "$episodes" -le 256 && "$fit" -ge 1 && "$fit" -lt "$episodes" && "$length" -ge 1 && "$length" -le 512 ]]
[[ "$(/usr/bin/head -c8 "$corpus/data.bin")" == PVDATA03 && "$(/usr/bin/stat -c%s "$corpus/data.bin")" -eq "$((32+episodes*length*21224))" ]]
data_sha="$(/usr/bin/sha256sum "$corpus/data.bin" | /usr/bin/cut -d' ' -f1)"
for ((i=0;i<episodes;i++));do
    hash="$(/usr/bin/sha256sum "$corpus/expert-$i/scene/case.json" | /usr/bin/cut -d' ' -f1)"
    env="$(/usr/bin/sha256sum "$corpus/expert-$i/scene/environment.bin" | /usr/bin/cut -d' ' -f1)"
    if (( i<fit ));then printf '%s\n' "$hash" >> "$out/fit.txt";printf '%s\n' "$env" >> "$out/fit-environments.txt";else printf '%s\n' "$hash" >> "$out/validation.txt";printf '%s\n' "$env" >> "$out/validation-environments.txt";fi
done
/usr/bin/sort -u "$out/fit.txt" > "$out/fit-unique.txt"
/usr/bin/sort -u "$out/validation.txt" > "$out/validation-unique.txt"
/usr/bin/comm -12 "$out/fit-unique.txt" "$out/validation-unique.txt" > "$out/overlap.txt"
/usr/bin/sort -u "$out/fit-environments.txt" > "$out/fit-environments-unique.txt"
/usr/bin/sort -u "$out/validation-environments.txt" > "$out/validation-environments-unique.txt"
/usr/bin/comm -12 "$out/fit-environments-unique.txt" "$out/validation-environments-unique.txt" > "$out/environment-overlap.txt"
/usr/bin/jq -n --arg sha "$data_sha" --argjson episodes "$episodes" --argjson fit "$fit" --argjson fitUnique "$(/usr/bin/wc -l < "$out/fit-unique.txt")" --argjson validationUnique "$(/usr/bin/wc -l < "$out/validation-unique.txt")" --argjson overlap "$(/usr/bin/wc -l < "$out/overlap.txt")" --argjson fitEnv "$(/usr/bin/wc -l < "$out/fit-environments-unique.txt")" --argjson validationEnv "$(/usr/bin/wc -l < "$out/validation-environments-unique.txt")" --argjson envOverlap "$(/usr/bin/wc -l < "$out/environment-overlap.txt")" '{dataSHA256:$sha,histories:$episodes,fitHistories:$fit,validationHistories:($episodes-$fit),uniqueFittingCaseHashes:$fitUnique,uniqueValidationCaseHashes:$validationUnique,caseHashesInBothSplits:$overlap,uniqueFittingEnvironmentHashes:$fitEnv,uniqueValidationEnvironmentHashes:$validationEnv,environmentHashesInBothSplits:$envOverlap,scope:"Exact case and environment file identity only; repeated cases may have different trajectories and different files may encode similar layouts"}' > "$out/result.json"
[[ "$(/usr/bin/sha256sum "$corpus/data.bin" | /usr/bin/cut -d' ' -f1)" == "$data_sha" ]]
echo 'Corpus case identity analysis completed.'
