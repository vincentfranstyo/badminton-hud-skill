"""Track players + shuttle in a static-camera badminton clip -> tracks.json for the HUD.

usage:
  python -I track.py VIDEO COURT.json OUT.json [--debug DIR]   full run (slow on CPU)
  python -I track.py --relink OUT.json                          redo shuttle linking only (seconds)
  python -I track.py --check VIDEO COURT.json OUT.png           draw court lines on frame 0 to verify COURT.json

COURT.json: {"points": [[[img_x, img_y], [world_x_m, world_y_m]], ...]}  (>= 4 points, source-video pixels)
World: x across court 0..6.1 m, y along court from near baseline 0 through net 6.7 to far baseline 13.4.
Writes OUT.json, OUT.js (for the HUD) and OUT-players.png: the frame where P1..P4 were assigned.
"""
import json, sys, math
import numpy as np, cv2

W, L, NET = 6.1, 13.4, 6.7
H = Hinv = None


def load_court(path):
    global H, Hinv
    pts = json.load(open(path))["points"]
    # ponytail: court points picked by hand per camera angle; upgrade = automatic court-line detection.
    H, _ = cv2.findHomography(np.float32([p for p, _ in pts]), np.float32([w for _, w in pts]))
    Hinv = np.linalg.inv(H)


def to_world(x, y):
    v = H @ [x, y, 1.0]
    return v[0] / v[2], v[1] / v[2]


def to_img(x, y):
    v = Hinv @ [x, y, 1.0]
    return v[0] / v[2], v[1] / v[2]


def in_court(wx, wy, m=1.2):
    return -m < wx < W + m and -m < wy < L + m


def main(src, out, debug=None):
    from ultralytics import YOLO
    from scipy.optimize import linear_sum_assignment
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    iw, ih = int(cap.get(3)), int(cap.get(4))
    model = YOLO("yolo11m.pt")
    bg = cv2.createBackgroundSubtractorMOG2(history=60, varThreshold=24, detectShadows=False)
    slots = None  # 4 player slots, world positions
    frames, raw_shuttle, all_boxes = [], [], []
    i = 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        r = model.predict(img, imgsz=1280, classes=[0], conf=0.15, verbose=False)[0]
        dets = []
        for (x1, y1, x2, y2), c in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist()):
            wx, wy = to_world((x1 + x2) / 2, y2)
            if in_court(wx, wy) and (y2 - y1) > 25:
                dets.append(dict(box=[x1, y1, x2, y2], foot=[(x1 + x2) / 2, y2], w=[wx, wy], conf=c))
        # keep 2 most confident per half (doubles)
        near = sorted([d for d in dets if d["w"][1] < NET], key=lambda d: -d["conf"])[:2]
        far = sorted([d for d in dets if d["w"][1] >= NET], key=lambda d: -d["conf"])[:2]
        dets = near + far
        if slots is None and len(dets) == 4:
            # P1/P2 = near side left->right, P3/P4 = far side left->right (as the camera sees it)
            first = sorted(dets, key=lambda d: (d["w"][1] >= NET, d["foot"][0]))
            slots = [d["w"] for d in first]
            label = img.copy()
            for k, d in enumerate(first):
                x1, y1, x2, y2 = map(int, d["box"])
                col = (255, 140, 60) if k < 2 else (80, 60, 255)
                cv2.rectangle(label, (x1, y1), (x2, y2), col, 2)
                ty = max(14, y1 - 6) if k % 2 == 0 else y2 + 20  # alternate above/below so close pairs stay readable
                cv2.putText(label, f"P{k + 1}", (x1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
            cv2.imwrite(out[:-5] + "-players.png", label)
            print(f"players assigned at frame {i} ({i / fps:.1f}s), see {out[:-5]}-players.png")
        players = [None] * 4
        if slots is not None and dets:
            cost = np.array([[math.dist(s, d["w"]) for d in dets] for s in slots])
            for si, di in zip(*linear_sum_assignment(cost)):
                if cost[si, di] < 2.5:
                    players[si] = dets[di]
                    slots[si] = dets[di]["w"]
        frames.append(players)

        # shuttle candidates: small bright moving blobs outside player bodies
        g = cv2.GaussianBlur(img, (3, 3), 0)
        fg = bg.apply(g)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        bright = cv2.inRange(hsv, (0, 0, 150), (180, 70, 255))
        m = cv2.bitwise_and(fg, bright)
        for d in dets + [dict(box=b) for b in r.boxes.xyxy.tolist()]:
            x1, y1, x2, y2 = map(int, d["box"])
            m[max(0, y1 + 8):y2, max(0, x1):x2] = 0  # body (keep head/racket band above)
        n, _, stats, cents = cv2.connectedComponentsWithStats(m)
        cands = [tuple(cents[k]) for k in range(1, n) if 2 <= stats[k, 4] <= 60]
        raw_shuttle.append(cands)
        all_boxes.append(r.boxes.xyxy.tolist())
        if debug and i % 15 == 0:
            dbg = img.copy()
            for p in players:
                if p:
                    cv2.rectangle(dbg, tuple(map(int, p["box"][:2])), tuple(map(int, p["box"][2:])), (0, 255, 255), 1)
            for c in cands:
                cv2.circle(dbg, tuple(map(int, c)), 4, (0, 0, 255), 1)
            for a, b in court_lines():
                cv2.line(dbg, tuple(map(int, to_img(*a))), tuple(map(int, to_img(*b))), (255, 0, 255), 1)
            cv2.imwrite(f"{debug}/f{i:04d}.png", dbg)
        i += 1

    json.dump(dict(cands=raw_shuttle, boxes=all_boxes), open(out + ".raw", "w"))  # for relink
    shuttle = link_shuttle(raw_shuttle, all_boxes)
    save(dict(fps=fps, w=iw, h=ih, n=len(frames), court=dict(W=W, L=L, NET=NET),
              H=H.tolist(), players=[[p and dict(box=[round(v, 1) for v in p["box"]],
                                                  w=[round(v, 2) for v in p["w"]]) for p in f] for f in frames],
              shuttle=shuttle), out)
    print(f"{len(frames)} frames, players seen {sum(any(f) for f in frames)}, shuttle pts {sum(s is not None for s in shuttle)}")


def court_lines():
    return [((0, 0), (W, 0)), ((0, L), (W, L)), ((0, 0), (0, L)), ((W, 0), (W, L)), ((0.46, 0), (0.46, L)),
            ((W - .46, 0), (W - .46, L)), ((0, NET), (W, NET)), ((0, NET - 1.98), (W, NET - 1.98)),
            ((0, NET + 1.98), (W, NET + 1.98)), ((W / 2, 0), (W / 2, NET - 1.98)), ((W / 2, NET + 1.98), (W / 2, L)),
            ((0, .76), (W, .76)), ((0, L - .76), (W, L - .76))]


def link_shuttle(raw, boxes, gate=28, max_acc=12, max_miss=3):
    """Constant-velocity chains over cleaned candidates; keep long, smooth, non-overlapping chains."""
    # 1) drop static flicker (same spot recurring nearby in time) and blobs on player bodies
    clean = []
    for t, cands in enumerate(raw):
        keep = []
        for c in cands:
            rec = sum(any(math.dist(c, o) < 4 for o in raw[k]) for k in range(max(0, t - 15), min(len(raw), t + 16)) if k != t)
            body = any(x1 < c[0] < x2 and y1 + 0.3 * (y2 - y1) < c[1] < y2 for x1, y1, x2, y2 in boxes[t])
            if rec < 4 and not body:
                keep.append(c)
        clean.append(keep)
    # 2) grow chains; reject jumps that break velocity
    tracks, live = [], []
    for t, cands in enumerate(clean):
        used = set()
        for tr in live:
            (t1, p1), v = tr["pts"][-1], tr["v"]
            dt = t - t1
            pred = (p1[0] + v[0] * dt, p1[1] + v[1] * dt)
            best = None
            for k, c in enumerate(cands):
                if k in used:
                    continue
                nv = ((c[0] - p1[0]) / dt, (c[1] - p1[1]) / dt)
                if len(tr["pts"]) > 1 and math.dist(nv, v) > max_acc:
                    continue
                d = math.dist(pred, c)
                if d < gate * dt and (best is None or d < best[0]):
                    best = (d, k, nv)
            if best:
                used.add(best[1])
                tr["v"] = best[2]
                tr["pts"].append((t, cands[best[1]]))
        for k, c in enumerate(cands):
            if k not in used:
                nt = dict(pts=[(t, c)], v=(0, 0))
                live.append(nt)
                tracks.append(nt)
        live = [tr for tr in live if t - tr["pts"][-1][0] <= max_miss]

    def ok(tr):
        p = [c for _, c in tr["pts"]]
        disp = math.dist(p[0], p[-1])
        steps = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(p, p[1:])]
        sp = [math.hypot(*s) for s in steps]
        path = sum(sp)
        # shuttle flight = fast + smooth: small mean turn between steps (arcs pass, jitter fails)
        turns = [abs(math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1]))
                 for u, v in zip(steps, steps[1:]) if math.hypot(*u) > 1 and math.hypot(*v) > 1]
        smooth = turns and sum(turns) / len(turns) < 0.7
        return len(p) >= 6 and disp > 85 and path / len(sp) > 6 and smooth

    out = [None] * len(raw)
    for tr in sorted(filter(ok, tracks), key=lambda tr: -len(tr["pts"])):  # longest first, no overwrite
        ts = [t for t, _ in tr["pts"]]
        if sum(out[t] is not None for t in ts) > 0.3 * len(ts):
            continue
        for (ta, a), (tb, b) in zip(tr["pts"], tr["pts"][1:] + [tr["pts"][-1]]):
            for t in range(ta, max(ta + 1, tb)):  # interpolate small gaps
                if out[t] is None:
                    f = (t - ta) / max(1, tb - ta)
                    out[t] = [round(a[0] + (b[0] - a[0]) * f, 1), round(a[1] + (b[1] - a[1]) * f, 1)]
    return out


def save(d, out):
    """tracks.json + tracks.js (composition loads data via <script>, no fetch)."""
    json.dump(d, open(out, "w"))
    open(out[:-5] + ".js", "w").write("window.TRACKS=" + json.dumps(d) + ";")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "--check":
        load_court(a[2])
        ok, img = cv2.VideoCapture(a[1]).read()
        for p, q in court_lines():
            cv2.line(img, tuple(map(int, to_img(*p))), tuple(map(int, to_img(*q))), (255, 0, 255), 2)
        sys.exit(cv2.imwrite(a[3], img) and print("wrote", a[3]))
    if a[0] == "--relink":  # re-run shuttle linking only: track.py --relink tracks.json
        d, raw = json.load(open(a[1])), json.load(open(a[1] + ".raw"))
        d["shuttle"] = link_shuttle(raw["cands"], raw["boxes"])
        save(d, a[1])
        sys.exit(print("shuttle pts", sum(s is not None for s in d["shuttle"])))
    load_court(a[1])
    main(a[0], a[2], a[4] if len(a) > 4 and a[3] == "--debug" else None)
