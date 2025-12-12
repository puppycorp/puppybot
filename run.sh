#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build/host"

cmake -S "$ROOT_DIR" -B "$BUILD_DIR"
cmake --build "$BUILD_DIR"

SERVER_URI=""
POSITIONAL_ARGS=()

DEFAULT_INSTANCE="puppybot-host"

while (($#)); do
	case "$1" in
	--server)
		if (($# < 2)); then
			echo "error: --server requires an argument" >&2
			exit 1
		fi
		SERVER_URI="$2"
		shift 2
		;;
	--)
		shift
		POSITIONAL_ARGS+=("$@")
		break
		;;
	*)
		POSITIONAL_ARGS+=("$1")
		shift
		;;
	esac
done

if ((${#POSITIONAL_ARGS[@]})); then
	set -- "${POSITIONAL_ARGS[@]}"
else
	set --
fi

resolve_uri() {
	local input="$1"
	local instance="${PUPPYBOT_INSTANCE_NAME:-$DEFAULT_INSTANCE}"
	# If the input already contains the bot path, keep it as-is.
	if [[ "$input" == *"/api/bot/"*"/ws" ]]; then
		echo "$input"
		return
	fi
	# Trim trailing slash and append the expected bot endpoint.
	input="${input%/}"
	echo "${input}/api/bot/${instance}/ws"
}

if [[ -n "$SERVER_URI" ]]; then
	SERVER_URI="$(resolve_uri "$SERVER_URI")"
	export PUPPYBOT_SERVER_URI="$SERVER_URI"
else
	SERVER_URI="${PUPPYBOT_SERVER_URI:-}"
fi

"$BUILD_DIR/puppybot" "$@"
