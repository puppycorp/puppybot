#!/usr/bin/env bash
# Check head reconstruction and reject unaudited or non-gated policies.
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
policy="$(realpath "${1:?Gated policy required}")";episode="$(realpath "${2:?Audited episode required}")";audit="$(realpath "${3:?Replay receipt required}")";nongated="$(realpath "${4:?Non-gated policy required}")";out="${5:?New output directory required}"
[[ ! -e "$out" ]];mkdir "$out";out="$(cd "$out" && pwd)";mkdir "$out/run" "$out/verified"
for file in "$episode"/actor-*.rgb "$episode"/actor-*.feedback "$episode/initial.json" "$episode/decisions.jsonl";do ln -s "$file" "$out/run/$(basename "$file")";done
cp "$audit" "$out/verified/result.json"
probe="$project/build/flex/control/large-phase-head-probe"
"$probe" "$policy" "$out/run" "$out/good" > "$out/good.log" 2>&1
jq -e '.actualCommandsReplayedExactly and .actorLogitsReconstructed and .maxLogitAbsError<0.0001 and .offlineCounterfactualOnly and .simulatorPhaseUsedOnlyForAnalysis and (.rows|length)>0' "$out/good/result.json" > /dev/null
frame="$(head -n1 "$episode/decisions.jsonl" | jq -r '.step')";rgb="$out/run/actor-$frame.rgb"
cp "$episode/actor-$frame.rgb" "$out/changed.rgb";byte="$(od -An -tu1 -j0 -N1 "$out/changed.rgb")";printf -v replacement '\\%03o' "$((byte^1))"
printf '%b' "$replacement" | dd of="$out/changed.rgb" bs=1 seek=0 conv=notrunc status=none
rm "$rgb";mv "$out/changed.rgb" "$rgb"
if "$probe" "$policy" "$out/run" "$out/bad-rgb" > "$out/bad-rgb.log" 2>&1;then echo 'A changed actor frame was accepted.' >&2;exit 1;fi
rg -Fq 'head probe RGB differs from recorded frame hash' "$out/bad-rgb.log"
rm "$rgb";ln -s "$episode/actor-$frame.rgb" "$rgb"
if "$probe" "$nongated" "$out/run" "$out/bad-nongated" > "$out/bad-nongated.log" 2>&1;then echo 'Non-gated policy was accepted.' >&2;exit 1;fi
rg -Fq 'head probe policy hash mismatch' "$out/bad-nongated.log"
jq '.passed=false' "$out/verified/result.json" > "$out/bad-audit.json";cp "$out/bad-audit.json" "$out/verified/result.json"
if "$probe" "$policy" "$out/run" "$out/bad-audit" > "$out/bad-audit.log" 2>&1;then echo 'Unaudited episode was accepted.' >&2;exit 1;fi
rg -Fq 'head probe requires an audited autonomous history' "$out/bad-audit.log"
echo 'Offline head probe reconstructs actor logits and rejects invalid inputs.'
