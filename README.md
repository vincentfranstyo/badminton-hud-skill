# badminton-hud-skill

An agent skill that turns a badminton rally clip into a game-style HUD video: a ring under each player, a card per player (name, speed, metres run), the shuttle's trail and speed, a mini court map, and a "Name, Name vs Name, Name" title. Players are tracked with YOLO, the shuttle with motion detection; the overlay is rendered with [HyperFrames](https://hyperframes.heygen.com).

```bash
npx skills add vincentfranstyo/badminton-hud-skill
```

Then ask your agent:

> make a badminton HUD for this clip: ~/Downloads/rally.mp4

It will map the court, track the rally, show you which player is P1-P4, ask for names, and render.

## Without an agent

```bash
cd skills/badminton-hud
python -I tools/track.py --check rally.mp4 court.json check.png   # court lines line up?
./make.sh rally.mp4 court.json work/                             # tracking (minutes on CPU)
cd work && npx --yes hyperframes@0.8.186 render -q high \
  --variables '{"p1":"Citot","p2":"VF","p3":"Erina","p4":"Vance"}' -o hud.mp4
```

`court.json` lists court-line crossings in the video and their real positions in metres; see `tools/court-example.json` and the skill for how to pick them.

Requires `uv`, `ffmpeg` and Node 22+. Works with a fixed camera and doubles. Shuttle speed is a 2-D estimate and reads low.

## License

MIT
