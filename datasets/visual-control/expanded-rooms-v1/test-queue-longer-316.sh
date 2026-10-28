#!/usr/bin/env bash
# Verify queue dependencies before allowing training to start.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root required}"
out="$(realpath -m "${1:?New output directory required}")";[[ ! -e "$out" ]]
mock="$out/mock";root="$mock/build/flex/sim/expanded-rooms-v1/large-model-v1"
mkdir -p "$root/memory-pose-316-v2" "$root/large-pose-screen-v2"
printf '0\n' > "$root/memory-pose-316-v2/run.exit";printf '0\n' > "$root/large-pose-screen-v2/run.exit"
cat > "$out/driver" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$PUPPYBOT_LONGER_316_WAIT_RUN" == "$PUPPYBOT_PROJECT/build/flex/sim/expanded-rooms-v1/large-model-v1/large-pose-screen-v2/run" ]]
mkdir "$PUPPYBOT_LONGER_316_OUT";printf 'called\n' > "$PUPPYBOT_LONGER_316_OUT/evidence"
EOF
queue="$project/datasets/visual-control/expanded-rooms-v1/queue-longer-316.sh"
PUPPYBOT_PROJECT="$mock" PUPPYBOT_LONGER_316_FROZEN_DRIVER="$out/driver" PUPPYBOT_LONGER_316_OUT="$out/training" PUPPYBOT_LONGER_316_QUEUE_OUT="$out/good" bash "$queue" > "$out/good.log" 2>&1
[[ -f "$out/training/evidence" && "$(< "$out/good/run.exit")" == 0 ]]
printf '1\n' > "$root/memory-pose-316-v2/run.exit"
if PUPPYBOT_PROJECT="$mock" PUPPYBOT_LONGER_316_FROZEN_DRIVER="$out/driver" PUPPYBOT_LONGER_316_OUT="$out/bad-training" PUPPYBOT_LONGER_316_QUEUE_OUT="$out/bad" bash "$queue" > "$out/bad.log" 2>&1;then echo 'Failed pose preparation was accepted.' >&2;exit 1;fi
[[ ! -e "$out/bad-training" && "$(< "$out/bad/run.exit")" != 0 ]]
echo 'Longer-training queue rejects failed pose preparation.'
