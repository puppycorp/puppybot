#!/usr/bin/env bash
# Matched scene audits must detect altered camera or own-feedback inputs.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]];mkdir "$out"
for name in baseline candidate;do
    root="$out/$name";mkdir "$root";printf '0\n' > "$root/run.exit"
    jq -n '{passed:true,episodes:8,auditedEpisodes:8,rows:[range(0;8)|{caseIndex:.,layoutId:(180+.),seed:(9980000+.),startPose:[.,0,0],auditPassed:true,suppliedMap:false,taskEventHint:false}]}' > "$root/score.json"
    for ((i=0;i<8;i++));do seed=$((9980000+i));run="$root/$i/$seed";mkdir -p "$run/scene" "$root/$i/verified"
        printf '{"step":295}\n' > "$run/initial.json";for file in case.json environment.bin;do printf 'scene %s %s\n' "$i" "$file" > "$run/scene/$file";done
        printf 'rgb %s\n' "$i" > "$run/actor-295.rgb";printf 'feedback %s\n' "$i" > "$run/actor-295.feedback"
        printf '{"passed":true,"commandReplayMaxAbsError":0,"taskEventHintAbsent":true}\n' > "$root/$i/verified/result.json"
    done
done
driver="$project/datasets/visual-control/expanded-rooms-v1/audit-matched-initial-inputs.sh"
bash "$driver" "$out/baseline" "$out/candidate" "$out/good" > "$out/good.log" 2>&1
jq -e '.passed and .episodes==8 and .sceneFilesIdentical and .initialActorImagesAndFeedbackIdentical and .policyReplaysPassed and .fullTrajectoriesNotClaimedIdentical' "$out/good/summary.json" > /dev/null
for suffix in rgb feedback;do
    file="$out/candidate/0/9980000/actor-295.$suffix";cp "$file" "$out/original-$suffix";printf 'changed\n' > "$file"
    if bash "$driver" "$out/baseline" "$out/candidate" "$out/bad-$suffix" > "$out/bad-$suffix.log" 2>&1;then echo "Changed $suffix was accepted." >&2;exit 1;fi
    [[ "$(< "$out/bad-$suffix/run.exit")" != 0 && ! -e "$out/bad-$suffix/summary.json" ]];cp "$out/original-$suffix" "$file"
done
echo 'Matched input audit rejects changed camera and feedback tensors.'
