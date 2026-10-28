#!/usr/bin/env bash
# Build an isolated simulator probe; the regular simulator is not modified.
set -euo pipefail
project="${PUPPYBOT_PROJECT:?Project root is required}"
out="${1:?A new output directory is required}"
[[ ! -e "$out" && -x "$project/build/flex/control/compiler" ]]
mkdir "$out"
cd "$project"
awk -v root="$project/flex/sim/" '
    /^import "/ {sub(/^import "/, ""); sub(/";$/, ""); print "import \"" root $0 "\";"; next}
    {sub(/^fn main\(argc, argv\)/, "fn ps_application_main(argc, argv)"); print}
' flex/sim/main.flex > "$out/probe.flex"
cat datasets/visual-control/expanded-rooms-v1/camera-pose-probe-tail.flex >> "$out/probe.flex"
build/flex/control/compiler "$out/probe.flex" -o "$out/probe"
sha256sum flex/sim/main.flex flex/sim/camera.flex datasets/visual-control/expanded-rooms-v1/camera-pose-probe-tail.flex "$out/probe" > "$out/inputs.sha256"
echo 'Built isolated camera pose probe: probe PITCH_DEG HEIGHT_MM RADIAL_MM'
