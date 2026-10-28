#!/usr/bin/env bash
set -euo pipefail

project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1/correction-probe-v1"
trap 'status=$?; printf "%s\n" "$status" > "$root/forward-epoch20.exit"' EXIT
printf '%s\n' "$BASHPID" > "$root/forward-epoch20.pid"
while [[ ! -f "$root/policy-20/receipt.json" ]];do
    [[ ! -f "$root/run.exit" ]] || { echo 'Probe training ended without the epoch-20 policy.';exit 1; }
    [[ -f "$root/run.pid" ]] && kill -0 "$(< "$root/run.pid")" || { echo 'Probe training disappeared.';exit 1; }
    /usr/bin/sleep 5
done
/usr/bin/cmp "$root/model/epoch-20.bin" "$root/policy-20/weights.bin"
export PATH="$root/native-path"
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
cd "$root/runtime"
./build/flex/control/forward-tests "$root/policy-20" "$root/subset/data.bin" "$root/forward-epoch20" > "$root/forward-epoch20.log" 2>&1
/usr/bin/jq -e '.passed and .logitMaxAbsError==0 and .memoryMaxAbsError==0 and .resetBitIdentical' "$root/forward-epoch20/result.json" > /dev/null
echo 'Epoch-20 exported policy exactly matches native training inference.'
