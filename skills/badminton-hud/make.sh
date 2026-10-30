#!/usr/bin/env bash
# usage: make.sh VIDEO COURT.json WORKDIR
# Copies the HUD template into WORKDIR, runs the tracker, leaves a project ready to render.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
video="$(realpath "$1")"; court="$(realpath "$2")"; work="$3"
mkdir -p "$work"; work="$(realpath "$work")"
venv="${BADMINTON_HUD_VENV:-$HOME/.cache/badminton-hud/venv}"
if [ ! -x "$venv/bin/python" ]; then
  uv venv -q "$venv" --python 3.12
  uv pip install -q --python "$venv/bin/python" -r "$here/tools/requirements.txt"
fi
cp "$here/template/"* "$work/"
ffmpeg -v error -y -i "$video" -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac "$work/rally.mp4"
dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$work/rally.mp4" | awk '{printf "%.2f", $1}')"
sed -i "s/__DUR__/$dur/g" "$work/index.html"
# run from an empty cwd: the model download lands in the cache, not next to untrusted input
cd "$(mktemp -d)"
"$venv/bin/python" -I "$here/tools/track.py" "$work/rally.mp4" "$court" "$work/tracks.json"
echo "ready: cd $work && npx --yes hyperframes@0.8.186 render -q high --variables '{\"p1\":\"..\",\"p2\":\"..\",\"p3\":\"..\",\"p4\":\"..\"}' -o out.mp4"
