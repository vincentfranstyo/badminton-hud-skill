---
name: badminton-hud
description: Turn a badminton rally clip (static camera, doubles) into a game-style HUD video - rings under each player, per-player cards (name, speed, distance run), shuttle trail + speed, mini court map, "Name, Name vs Name, Name" title. Tracks players (YOLO) and shuttle (motion blobs) offline, then renders with HyperFrames. Use when the user wants a badminton video with a HUD/overlay/stats, player tracking, shuttle speed, or a court map, or says "badminton hud".
---

# Badminton HUD

Static-camera doubles clip in, HUD MP4 out. Two parts:
- `tools/track.py` - detection + tracking -> `tracks.json` / `tracks.js`. Deterministic, no AI calls.
- `template/index.html` - HyperFrames composition that draws the HUD from `tracks.js`. Variables: names `p1..p4`, venue `venue`, team colours `colorA` / `colorB`.

`make.sh VIDEO COURT.json WORKDIR` does setup, copy, transcode and tracking in one go.

Needs: `uv`, `ffmpeg`, Node >= 22. First run creates a venv in `~/.cache/badminton-hud/venv` and downloads `yolo11m.pt` (~40 MB).

## Workflow

1. **Inspect the clip.** `ffprobe` size/fps/duration. Extract frame 0: `ffmpeg -i in.mp4 -frames:v 1 f0.png`. Camera must not move; if it pans, stop and tell the user (one court mapping per clip).
2. **Court points -> `court.json`.** Pick >= 4 (6 is better) court-line crossings visible in frame 0, in **source-video pixels**, paired with world metres (x across 0..6.1, y from near baseline 0 to far baseline 13.4, net 6.7). Useful world points: baseline corners (0,0)/(6.1,0), singles sideline x=0.46/5.64, doubles long service line y=0.76, short service line y=4.72 / 8.68, centre line x=3.05, net post foot (0 or 6.1, 6.7). Zoom with a grid to read pixels: `ffmpeg -i in.mp4 -frames:v 1 -vf "crop=...,scale=3*iw:-1,drawgrid=w=60:h=60:c=red@0.5" z.png`. Format: `tools/court-example.json`.
3. **Verify the court.** `python -I tools/track.py --check in.mp4 court.json check.png` and look at it: magenta lines must sit on the painted lines. Fix points until they do. Everything downstream (rings, map, distances) depends on this.
4. **Track.** `./make.sh in.mp4 court.json work/` (CPU: ~1.2 s per frame, so a 12 s clip is ~7 min - run in background). Prints the frame where players were assigned.
5. **Identity + look - ask before rendering.** Show the user `work/tracks-players.png`: four boxes labelled P1..P4 (P1/P2 = near side left->right; P3/P4 = far side left->right). Ask in one message: "Who is P1, P2, P3 and P4? What venue/court name should show? What two team colours?" Defaults: blue `#3b8bff` for P1/P2; red `#ff3b4e` for P3/P4. Don't guess names from appearance.
6. **Review the shuttle.** Plot `tracks.json` shuttle points on one frame and check they form flight arcs, not jitter on bodies/floor. Noise -> tune thresholds in `link_shuttle` (`disp`, mean-turn limit, `path/len(sp)`) and re-run `track.py --relink work/tracks.json` (seconds, no re-detection).
7. **Snapshot, then render.**
   ```sh
   cd work
   V='{"p1":"A","p2":"B","p3":"C","p4":"D","venue":"Petojo Arena Court","colorA":"#3b8bff","colorB":"#ff3b4e"}'
   npx --yes hyperframes@0.8.186 snapshot --at 1,5 --variables "$V"   # read the PNGs
   npx --yes hyperframes@0.8.186 render -q high --variables "$V" -o hud.mp4
   ```
   Render failing with `Invalid JPEG input at frame 0: empty frame` is a capture flake - just rerun.

## How the numbers are made (tell the user when asked)

- **Court mapping:** homography from the hand-picked points maps any floor pixel to court metres.
- **Player position:** bottom-centre of the person box (feet) -> court metres. Two most confident detections per half; identity kept by nearest-match (Hungarian) to the previous position. Smoothed ±4 frames.
- **Distance run:** sum of frame-to-frame moves of the smoothed position. **Player speed:** that move x fps, averaged over 9 frames, in km/h.
- **Shuttle:** bright, moving, small blobs outside player bodies, linked into smooth fast chains; short/jittery chains dropped. Speed = pixels/frame x (1.75 m / nearest player's box height) x fps. 2-D only: motion toward/away from camera is invisible, so it **reads low** (real smashes 200-400 km/h).
- **Status bar:** cosmetic - falls with distance run. Not real fatigue.

## Limits

Fixed camera only. Doubles (4 players) assumed. Players crossing/occluding can swap identities. Fast flat shuttle exchanges near the net are often missed. Not real-time: this is an offline pipeline.
