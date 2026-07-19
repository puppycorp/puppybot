#!/usr/bin/env bash
# Attach the native Tinygrad V6 policy to an already-running PuppyBot runtime.

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
puppybot_dir="$(cd -- "$script_dir/.." && pwd)"
project_dir="$(cd -- "$puppybot_dir/.." && pwd)"
python_bin="$project_dir/.venv/bin/python"
checkpoint="$project_dir/workdir/training-dataset/tinygrad-v6-grid-018/bottle-v6-grid.safetensors"
base_url="${PUPPYBOT_RUNTIME_URL:-http://127.0.0.1:8080}"
if [[ -n "${PUPPYBOT_RUNTIME_URL:-}" ]]; then
    base_url_source="PUPPYBOT_RUNTIME_URL"
else
    # 8080 is the runtime HTTP/WebSocket API.  The separately configured WGUI
    # dashboard normally uses 8081 and does not own the detector API.
    base_url_source="default runtime API port 8080"
fi
bin_x="-0.52"
bin_y="0.32"
artifacts=""
preview=1
rate_samples=""

usage() {
    cat <<'EOF'
Usage: scripts/attach-tinygrad-v6-detector.sh [OPTIONS]

Attach the native Tinygrad V6 TCP-camera detector to an already-running local
PuppyBot runtime. This script never starts or stops the runtime. By default it
opens a live local preview of the exact inferred TCP frame with detector boxes.

Options:
  --base-url URL                  Runtime API URL (default: http://127.0.0.1:8080)
  --bin-x METRES                  Known bin world X (default: -0.52)
  --bin-y METRES                  Known bin world Y (default: 0.32)
  --artifacts PATH                New policy artifact directory
  --measure-tcp-rate-samples N    Capture/inference measurement only (N >= 3)
  --no-preview                    Do not open the local detector preview
  --help, -h                      Show this help

Only plain HTTP URLs on 127.0.0.1 or localhost are accepted. The runtime
accepts TCP-camera frames only from a loopback socket peer, even when its UI
listens on the LAN. Without --artifacts, a unique empty directory is created under
puppybot/workdir/recordings/. Closing the preview requests drive and arm stop,
then exits the attached policy; it never stops the simulator.

The detector attaches to the runtime API (normally port 8080), not the WGUI
dashboard (normally port 8081). Override with --base-url or PUPPYBOT_RUNTIME_URL
only when the runtime API itself was intentionally configured on another port.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --base-url)
            [[ $# -ge 2 ]] || { echo "--base-url requires a URL" >&2; exit 2; }
            base_url="$2"
            base_url_source="--base-url"
            shift 2
            ;;
        --bin-x)
            [[ $# -ge 2 ]] || { echo "--bin-x requires metres" >&2; exit 2; }
            bin_x="$2"
            shift 2
            ;;
        --bin-y)
            [[ $# -ge 2 ]] || { echo "--bin-y requires metres" >&2; exit 2; }
            bin_y="$2"
            shift 2
            ;;
        --artifacts)
            [[ $# -ge 2 ]] || { echo "--artifacts requires a path" >&2; exit 2; }
            artifacts="$2"
            shift 2
            ;;
        --measure-tcp-rate-samples)
            [[ $# -ge 2 ]] || { echo "--measure-tcp-rate-samples requires a count" >&2; exit 2; }
            rate_samples="$2"
            shift 2
            ;;
        --no-preview)
            preview=0
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

# The attachment sensor/control surface is intentionally local-only. Validate
# this before creating an artifact directory or launching any policy command.
if [[ ! "$base_url" =~ ^http://(127\.0\.0\.1|localhost)(:[0-9]{1,5})?/?$ ]]; then
    echo "refusing non-loopback or malformed --base-url: $base_url" >&2
    echo "use plain http://127.0.0.1:PORT or http://localhost:PORT" >&2
    exit 2
fi

[[ "$bin_x" =~ ^-?([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]] || { echo "--bin-x must be a finite decimal metres value" >&2; exit 2; }
[[ "$bin_y" =~ ^-?([0-9]+([.][0-9]*)?|[.][0-9]+)$ ]] || { echo "--bin-y must be a finite decimal metres value" >&2; exit 2; }
if [[ -n "$rate_samples" && ! "$rate_samples" =~ ^[0-9]+$ ]]; then
    echo "--measure-tcp-rate-samples must be a whole number" >&2
    exit 2
fi
[[ -x "$python_bin" ]] || { echo "Tinygrad Python is unavailable: $python_bin" >&2; exit 1; }
[[ -f "$checkpoint" ]] || { echo "Tinygrad V6 checkpoint is unavailable: $checkpoint" >&2; exit 1; }

# Verify the exact camera endpoint before creating artifacts or loading Tinygrad.
# The runtime checks the TCP peer itself; this loopback request works whether
# the simulator listener is bound to 127.0.0.1 or 0.0.0.0.
preflight_body="$(mktemp)"
trap 'rm -f "$preflight_body"' EXIT
if ! preflight_status="$(curl --silent --show-error --max-time 3 \
    --output "$preflight_body" --write-out '%{http_code}' \
    "$base_url/api/autonomy/observations/tcp/raw")"; then
    echo "could not reach the PuppyBot TCP-camera endpoint at $base_url" >&2
    echo "start the simulator first, for example:" >&2
    echo "  ./scripts/run-runtime.sh --sim" >&2
    exit 1
fi
if [[ "$preflight_status" != "200" ]]; then
    echo "TCP-camera preflight failed (HTTP $preflight_status): $base_url/api/autonomy/observations/tcp/raw" >&2
    echo "ensure this is a running PuppyBot --sim runtime and this script is using a loopback URL" >&2
    exit 1
fi
if ! grep -q 'puppybot.runtime.tcp-raw-observation.v1' "$preflight_body"; then
    echo "TCP-camera preflight reached an unexpected service: $base_url" >&2
    echo "the detector needs the runtime API (normally http://127.0.0.1:8080), not the WGUI dashboard (normally port 8081)" >&2
    exit 1
fi
rm -f "$preflight_body"
trap - EXIT

if [[ -n "$artifacts" && "$artifacts" != /* ]]; then
    artifacts="$PWD/$artifacts"
fi
if [[ -z "$artifacts" ]]; then
    recordings_dir="$puppybot_dir/workdir/recordings"
    mkdir -p "$recordings_dir"
    artifacts="$(mktemp -d "$recordings_dir/tinygrad-v6-attached-XXXXXX")"
elif [[ -e "$artifacts" ]]; then
    echo "artifacts path already exists; choose a new path: $artifacts" >&2
    exit 2
fi

policy_args=(
    scenarios/bottle_to_bin_yolo.py
    --detector tinygrad-v6
    --tinygrad-model "$checkpoint"
    --tinygrad-threshold 0.40
    --artifacts "$artifacts"
    --base-url "$base_url"
    --bin-x "$bin_x"
    --bin-y "$bin_y"
)
if [[ "$preview" -eq 1 ]]; then
    policy_args+=(--preview)
fi
if [[ -n "$rate_samples" ]]; then
    policy_args+=(--measure-tcp-rate-samples "$rate_samples")
fi

echo "Attaching Tinygrad V6 detector to runtime API: $base_url ($base_url_source)"
echo "Dashboard note: WGUI is normally http://127.0.0.1:8081; detector frames/control use the runtime API above."
echo "Policy artifacts: $artifacts"
echo "This script does not manage the PuppyBot runtime."
cd "$puppybot_dir"
exec "$python_bin" "${policy_args[@]}"
