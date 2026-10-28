#!/usr/bin/env bash
# Check search destinations against recorded observations and room geometry.
set -euo pipefail
project="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
episode="$(cd "${1:?Episode directory required}" && pwd)"
output="${2:?New output directory required}"
source_scene="$(jq -er 'select(.searchTeacher=="coverage-camera-v1" and .teacherUsesRoomBounds and (if has("searchGoalsUseUnseenBrickPosition") then .searchGoalsUseUnseenBrickPosition==false else .teacherReadsUnseenBrickPosition==false end)) | .sourceScene' "$episode/supervision.json")"
[[ -f "$source_scene/layout.json" ]]
cmp "$source_scene/case.json" "$episode/scene/case.json"
cmp "$source_scene/environment.bin" "$episode/scene/environment.bin"
mkdir "$output"
sha256sum "$episode/initial.json" "$episode/decisions.jsonl" "$episode/teacher-search.jsonl" "$episode/supervision.json" "$episode/scene/case.json" "$episode/scene/environment.bin" "$source_scene/layout.json" "$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher.jq" > "$output/inputs.sha256"
jq -n --slurpfile initial "$episode/initial.json" --slurpfile layout "$source_scene/layout.json" --slurpfile trace "$episode/teacher-search.jsonl" --slurpfile decisions "$episode/decisions.jsonl" -f "$project/datasets/visual-control/expanded-rooms-v1/audit-coverage-teacher.jq" > "$output/result.json"
jq -e '.passed and .steps>=1 and .reconstructedFromRoomBoundsAndRecordedCamera and .oracleLabelsMatched and .actorInputsUnchanged and .teacherGeometryPrivileged and .brickPositionNotReadBySearchReconstruction and (.independentTeacherExecutionReplay|not)' "$output/result.json" > /dev/null
sha256sum -c "$output/inputs.sha256" > "$output/integrity.log"
