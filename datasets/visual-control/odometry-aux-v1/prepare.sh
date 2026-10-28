#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/odometry-aux-v1"
source="$project/build/flex/sim/late-search-v1/artifacts-v2/data172"
[[ ! -e "$root/prepare.exit" && ! -e "$root/targets" ]]
trap 'status=$?; printf "%s\n" "$status" > "$root/prepare.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/prepare.pid"
"$root/targets-tool" prepare "$source/data.bin" "$source" "$root/targets" > "$root/prepare-native.log" 2>&1
"$root/targets-tool" verify "$source/data.bin" "$source" "$root/targets/targets.bin" "$root/verified.json" > "$root/verify-native.log" 2>&1
/usr/bin/jq -e '.passed and .episodes==172 and .inverseTransformAndYawChecked and .actorInputsUnchanged' "$root/verified.json" > /dev/null
sha="$(/usr/bin/sha256sum "$root/targets/targets.bin" | /usr/bin/cut -d' ' -f1)"
/usr/bin/jq -e --arg sha "$sha" '.prepared and .targetsSHA256==$sha and .sourceDataSHA256=="05032e0eb2a4a98a7f0146db66195792b2c22fe3bda3138039e9c721bc69b284"' "$root/targets/report.json" > /dev/null
/usr/bin/jq -e --arg sha "$sha" '.targetsSHA256==$sha' "$root/verified.json" > /dev/null
echo 'Relative-pose supervision prepared and independently checked against every physical trace; no model uses it yet.'
