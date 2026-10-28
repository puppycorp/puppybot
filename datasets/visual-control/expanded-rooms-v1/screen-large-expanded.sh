#!/usr/bin/env bash
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
root="$project/build/flex/sim/expanded-rooms-v1/large-model-v1"
while [[ ! -f "$root/expanded-236.exit" ]]; do
    [[ -f "$root/expanded-236.pid" ]] && kill -0 "$(< "$root/expanded-236.pid")" || { echo 'Training exited without a status.' >&2; exit 1; }
    /usr/bin/sleep 20
done
[[ "$(< "$root/expanded-236.exit")" == 0 ]] || { echo 'Training failed; screen not started.' >&2; exit 1; }
export PUPPYBOT_POLICY="$root/expanded-236"
export PUPPYBOT_SCREEN_OUTPUT="$root/expanded-236-screen"
/usr/bin/bash "$root/source/datasets/screen-large-model.sh"
