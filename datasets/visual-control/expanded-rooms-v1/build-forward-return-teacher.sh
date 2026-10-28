#!/usr/bin/env bash
# Build an isolated teacher that penalizes reverse only after brick consumption.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${PUPPYBOT_FORWARD_TEACHER_BUILD:?New output directory required}")"
compiler="${PUPPYBOT_FORWARD_TEACHER_COMPILER:?Native compiler required}"
[[ ! -e "$out" ]];mkdir "$out"
mkdir -p "$out/source/build/flex/sim"
cp -a "$project/flex" "$out/source/flex"
cp -a "$project/build/flex/sim/library" "$out/source/build/flex/sim/library"
cmp "$project/build/flex/sim/dependencies.flex" <(printf 'import "%s/build/flex/sim/library/libs/render.flex";\nimport "%s/build/flex/sim/library/libs/physics/physics.flex";\n' "$project" "$project")
cmp "$project/build/flex/sim/library/lib/f64.flex" <(printf 'import "%s/flex/core/words.flex";\n' "$project")
printf 'import "library/libs/render.flex";\nimport "library/libs/physics/physics.flex";\n' > "$out/source/build/flex/sim/dependencies.flex"
printf 'import "%s";\n' "$out/source/flex/core/words.flex" > "$out/source/build/flex/sim/library/lib/f64.flex"
sha256sum "$compiler" "$project/build/flex/sim/dependencies.flex" > "$out/inputs.sha256"
find "$project/flex" -type f -name '*.flex' -print0 | sort -z | xargs -0 -r sha256sum >> "$out/inputs.sha256"
find "$project/build/flex/sim/library" -type f -print0 | sort -z | xargs -0 -r sha256sum >> "$out/inputs.sha256"
"$compiler" "$out/source/flex/sim/main.flex" -o "$out/reference-simulator"
navigation="$out/source/flex/sim/navigation.flex";agent="$out/source/flex/sim/agent.flex"
old='if action % 6 >= 3 { cost = f64_mul(cost, ps_number(15, 10)); }'
new='if action % 6 >= 3 { let factor = ps_number(15, 10); if ps_nav_training_oracle && ps_seek_found { factor = ps_number(4, 1); } cost = f64_mul(cost, factor); }'
[[ "$(rg -F -c "$old" "$navigation")" == 1 ]]
OLD_TEACHER_TEXT="$old" NEW_TEACHER_TEXT="$new" perl -0pi -e 's/\Q$ENV{OLD_TEACHER_TEXT}\E/$ENV{NEW_TEACHER_TEXT}/' "$navigation"
old='ps_oracle_key_word(ps_x); ps_oracle_key_word(ps_y); ps_oracle_key_word(ps_heading);'
new='ps_oracle_key_word(ps_seek_found); ps_oracle_key_word(ps_x); ps_oracle_key_word(ps_y); ps_oracle_key_word(ps_heading);'
[[ "$(rg -F -c "$old" "$agent")" == 1 ]]
OLD_TEACHER_TEXT="$old" NEW_TEACHER_TEXT="$new" perl -0pi -e 's/\Q$ENV{OLD_TEACHER_TEXT}\E/$ENV{NEW_TEACHER_TEXT}/' "$agent"
"$compiler" "$out/source/flex/sim/main.flex" -o "$out/forward-return-simulator"
! cmp -s "$out/reference-simulator" "$out/forward-return-simulator"
sha256sum -c "$out/inputs.sha256" > "$out/integrity.log"
sha256sum "$out/reference-simulator" "$out/forward-return-simulator" "$navigation" "$agent" > "$out/outputs.sha256"
jq -n --arg reference "$(sha256sum "$out/reference-simulator" | cut -d' ' -f1)" --arg candidate "$(sha256sum "$out/forward-return-simulator" | cut -d' ' -f1)" '{passed:true,referenceSimulatorSHA256:$reference,forwardReturnSimulatorSHA256:$candidate,defaultReverseCost:1.5,teacherReturnReverseCost:4.0,searchAndStudentCostsUnchanged:true,reverseStillPermitted:true,oracleCacheKeysIncludePhase:true,sourceSnapshotOnly:true,trainingOracleOnly:true,automaticPromotion:false}' > "$out/summary.json"
echo 'Built isolated reference and forward-preferring return teacher simulators.'
