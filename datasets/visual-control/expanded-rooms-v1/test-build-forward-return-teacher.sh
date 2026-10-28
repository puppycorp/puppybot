#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
mock="$out/mock";mkdir -p "$mock/flex/sim" "$mock/flex/core" "$mock/build/flex/sim/library/lib"
printf 'import "navigation.flex";\n' > "$mock/flex/sim/main.flex"
printf 'if action %% 6 >= 3 { cost = f64_mul(cost, ps_number(15, 10)); }\n' > "$mock/flex/sim/navigation.flex"
printf 'ps_oracle_key_word(ps_x); ps_oracle_key_word(ps_y); ps_oracle_key_word(ps_heading);\n' > "$mock/flex/sim/agent.flex"
printf 'source\n' > "$mock/flex/core/words.flex"
printf 'import "%s/build/flex/sim/library/libs/render.flex";\nimport "%s/build/flex/sim/library/libs/physics/physics.flex";\n' "$mock" "$mock" > "$mock/build/flex/sim/dependencies.flex"
printf 'import "%s/flex/core/words.flex";\n' "$mock" > "$mock/build/flex/sim/library/lib/f64.flex"
cat > "$out/compiler" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$2" == -o ]]
if rg -Fq 'if ps_nav_training_oracle && ps_seek_found { factor = ps_number(4, 1); }' "$(dirname "$1")/navigation.flex";then printf 'candidate\n' > "$3";else printf 'reference\n' > "$3";fi
EOF
chmod +x "$out/compiler"
driver="$project/datasets/visual-control/expanded-rooms-v1/build-forward-return-teacher.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_FORWARD_TEACHER_COMPILER="$out/compiler" PUPPYBOT_FORWARD_TEACHER_BUILD="$out/good" bash "$driver" > "$out/good.log"
jq -e '.passed and .teacherReturnReverseCost==4 and .defaultReverseCost==1.5 and .searchAndStudentCostsUnchanged and .reverseStillPermitted and .oracleCacheKeysIncludePhase and .sourceSnapshotOnly and .trainingOracleOnly and (.automaticPromotion|not)' "$out/good/summary.json" > /dev/null
rg -Fq 'ps_oracle_key_word(ps_seek_found);' "$out/good/source/flex/sim/agent.flex"
! rg -Fq 'ps_seek_found' "$mock/flex/sim/navigation.flex" "$mock/flex/sim/agent.flex"
printf 'unexpected navigation source\n' > "$mock/flex/sim/navigation.flex"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_FORWARD_TEACHER_COMPILER="$out/compiler" PUPPYBOT_FORWARD_TEACHER_BUILD="$out/bad" bash "$driver" > "$out/bad.log" 2>&1;then echo 'Builder accepted unexpected navigation source.' >&2;exit 1;fi
[[ ! -e "$out/bad/summary.json" ]]
echo 'Forward-return teacher build scopes its cost and rejects unexpected source.'
