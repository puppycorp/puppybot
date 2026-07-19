#!/usr/bin/env bash
# Run one seeded PuppyBot bottle-to-bin simulation with the native Tinygrad V6 detector.

set -euo pipefail

# GUI terminals launched from a Flatpak (notably Zed) can leak their private
# loader path into child processes.  That makes ordinary host tools such as
# `mkdir` and the Rust simulator resolve incompatible Flatpak libraries.  The
# episode runs host Python/Cargo, so deliberately use the host loader search
# path for this process tree.
unset LD_LIBRARY_PATH

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
puppybot_dir="$(cd -- "$script_dir/.." && pwd)"
project_dir="$(cd -- "$puppybot_dir/.." && pwd)"
python_bin="$project_dir/.venv/bin/python"
checkpoint="$project_dir/workdir/training-dataset/tinygrad-v6-grid-018/bottle-v6-grid.safetensors"
seed=20260719
artifacts=""
preview=1

usage() {
    cat <<'EOF'
Usage: scripts/run-tinygrad-v6-sim-episode.sh [--seed N] [--artifacts PATH] [--preview|--no-preview] [--record-tcp-episode]

Verified recording command (fresh seed-42 Tinygrad episode):
  ./scripts/run-tinygrad-v6-sim-episode.sh --seed 42 --no-preview --record-tcp-episode

Runs the native Tinygrad V6 wrist-camera detector in one seeded PuppyBot
simulator episode. By default, it opens a local OpenCV preview showing the
exact TCP frame used for inference with its detector annotation. The simulator
itself stays headless: the policy owns the separate preview window.

Use --no-preview for CI, recording, or an otherwise non-graphical shell.
Without --artifacts the script creates a new, empty directory under
workdir/recordings/ and never removes it. Closing the preview safety-stops the
policy and ends the episode as an intentional operator-stopped result.

--record-tcp-episode writes one continuous annotated MP4 from the simulated
TCP/wrist camera for the full state-machine episode. It keeps only a compact
5-fps TCP pose trace while the policy controls the robot, then starts the
replay renderer/MP4 encoder only after the completion judge passes. Recording
is intended for --no-preview automation. A successful run writes:
  <artifacts>/continuous-video/continuous-tcp-tinygrad-v6.mp4
  <artifacts>/continuous-video/continuous-tcp-tinygrad-v6.manifest.json
The manifest links the replay trace, Tinygrad V6 detector, and passing judge.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --seed)
            [[ $# -ge 2 ]] || { echo "--seed requires a value" >&2; exit 2; }
            seed="$2"
            shift 2
            ;;
        --artifacts)
            [[ $# -ge 2 ]] || { echo "--artifacts requires a path" >&2; exit 2; }
            artifacts="$2"
            shift 2
            ;;
        --preview)
            preview=1
            shift
            ;;
        --no-preview)
            preview=0
            shift
            ;;
        --record-tcp-episode)
            record_tcp_episode=1
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

[[ "$seed" =~ ^[0-9]+$ ]] || { echo "--seed must be a non-negative integer" >&2; exit 2; }
[[ -x "$python_bin" ]] || { echo "Tinygrad Python is unavailable: $python_bin" >&2; exit 1; }
[[ -f "$checkpoint" ]] || { echo "Tinygrad V6 checkpoint is unavailable: $checkpoint" >&2; exit 1; }
if [[ -n "$artifacts" && "$artifacts" != /* ]]; then
    artifacts="$PWD/$artifacts"
fi

if [[ -z "$artifacts" ]]; then
    recordings_dir="$puppybot_dir/workdir/recordings"
    mkdir -p "$recordings_dir"
    for _ in $(seq 1 100); do
        candidate="$recordings_dir/tinygrad-v6-episode-$(date +%Y%m%d-%H%M%S)-$RANDOM-$RANDOM"
        if [[ ! -e "$candidate" ]]; then
            artifacts="$candidate"
            break
        fi
    done
    [[ -n "$artifacts" ]] || { echo "could not reserve a unique artifacts path" >&2; exit 1; }
elif [[ -e "$artifacts" ]]; then
    echo "artifacts path already exists; choose a new path: $artifacts" >&2
    exit 2
fi

echo "Tinygrad V6 checkpoint: $checkpoint"
echo "Episode artifacts: $artifacts"
if [[ "$preview" -eq 1 ]]; then
    echo "Live TCP detector preview: enabled (close it to safety-stop and end the episode)"
else
    echo "Live TCP detector preview: disabled"
fi
if [[ "${record_tcp_episode:-0}" -eq 1 ]]; then
    echo "Continuous TCP episode recording: enabled"
fi

cd "$puppybot_dir"
episode_args=(
    scenarios/run_bottle_to_bin_episode.py
    --detector tinygrad-v6
    --tinygrad-model "$checkpoint"
    --tinygrad-threshold 0.40
    --policy-python "$python_bin"
    --seed "$seed"
    --artifacts "$artifacts"
)
if [[ "$preview" -eq 1 ]]; then
    episode_args+=(--preview)
fi
if [[ "${record_tcp_episode:-0}" -eq 1 ]]; then
    episode_args+=(--record-postrun-tcp-replay)
fi
exec "$python_bin" "${episode_args[@]}"
