#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$ROOT_DIR/build/host"

cmake -S "$ROOT_DIR" -B "$BUILD_DIR"
cmake --build "$BUILD_DIR"

SERVER_URI=""
POSITIONAL_ARGS=()

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

if [[ -n "$SERVER_URI" ]]; then
	PUPPYBOT_SERVER_URI="$SERVER_URI" "$BUILD_DIR/puppybot" "$@"
else
	"$BUILD_DIR/puppybot" "$@"
fi
