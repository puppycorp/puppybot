#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
asset_dir="$project_dir/build/flex/vision"
mkdir -p "$asset_dir"
python3 -m venv "$project_dir/build/flex/vision-env"
"$project_dir/build/flex/vision-env/bin/pip" install -r "$project_dir/flex/vision/requirements-validation.txt"
curl -fL --retry 2 'https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.onnx' -o "$asset_dir/yolo26n.onnx.tmp"
echo '2e947b787d9e787b93a16772a5f55b1d4d8c4d86f53146149c5d6a642442d6f7'"  $asset_dir/yolo26n.onnx.tmp" | sha256sum -c -
mv "$asset_dir/yolo26n.onnx.tmp" "$asset_dir/yolo26n.onnx"
"$project_dir/build/flex/vision-env/bin/python" "$project_dir/flex/scripts/import-yolo.py" "$asset_dir/yolo26n.onnx" "$asset_dir/yolo26n"
cmp "$asset_dir/yolo26n/model.pup" "$project_dir/flex/vision/models/yolo26n.pup"
curl -fL --retry 2 'https://raw.githubusercontent.com/ultralytics/assets/main/im/bus.jpg' -o "$asset_dir/bus.jpg.tmp"
echo 'c02019c4979c191eb739ddd944445ef408dad5679acab6fd520ef9d434bfbc63'"  $asset_dir/bus.jpg.tmp" | sha256sum -c -
mv "$asset_dir/bus.jpg.tmp" "$asset_dir/bus.jpg"
"$project_dir/build/flex/vision-env/bin/python" "$project_dir/flex/scripts/vision-fixtures.py"
echo "Prepared native Pup checkpoint: $asset_dir/yolo26n/model.json"
