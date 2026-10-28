#!/usr/bin/env bash
# Check feedback counterfactuals and reject unaudited or wrong-width policies.
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
policy="$(realpath "${1:?Large policy required}")";episode="$(realpath "${2:?Audited episode required}")";audit="$(realpath "${3:?Replay receipt required}")";wrongwidth="$(realpath "${4:?Wrong-width policy required}")";out="${5:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out";out="$(cd "$out" && pwd)";mkdir "$out/run" "$out/verified"
for file in "$episode"/actor-*.rgb "$episode"/actor-*.feedback "$episode/initial.json" "$episode/decisions.jsonl";do ln -s "$file" "$out/run/$(basename "$file")";done
cp "$audit" "$out/verified/result.json"
probe="$project/build/flex/control/large-feedback-probe"
"$probe" "$policy" "$out/run" "$out/good" > "$out/good.log" 2>&1
jq -e '.actualCommandsReplayedExactly and .counterfactualDidNotAlterServerState and .neutralFeedbackHypothetical and .offlineCounterfactualOnly and .simulatorPhaseUsedOnlyForAnalysis and (.rows|length)>0' "$out/good/result.json" > /dev/null
frame="$(head -n1 "$episode/decisions.jsonl" | jq -r '.step')";rgb="$out/run/actor-$frame.rgb"
cp "$episode/actor-$frame.rgb" "$out/changed.rgb";byte="$(od -An -tu1 -j0 -N1 "$out/changed.rgb")";printf -v replacement '\\%03o' "$((byte^1))"
printf '%b' "$replacement" | dd of="$out/changed.rgb" bs=1 seek=0 conv=notrunc status=none
rm "$rgb";mv "$out/changed.rgb" "$rgb"
if "$probe" "$policy" "$out/run" "$out/bad-rgb" > "$out/bad-rgb.log" 2>&1;then echo 'A changed actor frame was accepted.' >&2;exit 1;fi
rg -Fq 'feedback probe RGB differs from recorded frame hash' "$out/bad-rgb.log"
rm "$rgb";ln -s "$episode/actor-$frame.rgb" "$rgb"
if "$probe" "$wrongwidth" "$out/run" "$out/bad-wrongwidth" > "$out/bad-wrongwidth.log" 2>&1;then echo 'Wrong-width policy was accepted.' >&2;exit 1;fi
rg -Fq 'feedback probe policy hash mismatch' "$out/bad-wrongwidth.log"
jq '.passed=false' "$out/verified/result.json" > "$out/bad-audit.json";cp "$out/bad-audit.json" "$out/verified/result.json"
if "$probe" "$policy" "$out/run" "$out/bad-audit" > "$out/bad-audit.log" 2>&1;then echo 'Unaudited episode was accepted.' >&2;exit 1;fi
rg -Fq 'feedback probe requires an audited autonomous history' "$out/bad-audit.log"
echo 'Offline feedback probe replays actual inputs consistently and rejects invalid inputs.'
