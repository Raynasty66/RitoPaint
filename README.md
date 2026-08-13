# RiotPaint

A transparent, always-on-top overlay for League of Legends replays. Draw on the
map and the marks stay pinned to the ground as the camera pans.

Marks are stored as **world coordinates**, not screen pixels. Every frame, each
point is re-projected through a model of the observer camera — so a circle drawn
around the dragon pit stays on the dragon pit.

## Requirements

- Windows
- Python 3.10+
- League of Legends with the Replay API enabled (it serves on `https://127.0.0.1:2999`)
- **League set to Windowed or Borderless, not Fullscreen** — in exclusive
  fullscreen the game has no drawable window for the overlay to align to. Its
  window reports 2x2 and the overlay ends up 1 pixel wide, or 0 and it crashes.

## Install

```
pip install -r requirements.txt
```

### Enable the Replay API

It is off by default, and every `/replay/*` endpoint returns `Not Found` until
it is on. With League **fully closed** — the client rewrites this file when it
exits, so an edit made while it is running gets thrown away:

```
python ../scripts/enable_replay_api.py
```

That sets `EnableReplayApi=1` under `[General]` in
`C:\Riot Games\League of Legends\Config\game.cfg`. Verify it took:

```
curl -k https://127.0.0.1:2999/replay/render
```

with a replay playing — camera JSON means it is working. No Riot developer key
is involved: this is a local server inside the game process, not the public web
API at `api.riotgames.com`, and it needs no auth.

## Run

Load a replay and start playback in **windowed** mode, then:

```
python draw_overlay.py
```

It prints the rect it aligned to. That should match League's window - if it
prints your full screen size, or a 1x1, no gameplay window was found. Run
`python check_alignment.py` to see every candidate window and which one won.

The overlay starts click-through, so League stays fully usable until you switch
to draw mode. Global hotkeys may require running as administrator.

## Controls

| key | |
|---|---|
| `` ` `` | toggle draw mode / click-through |
| `.` | toggle the brush dock |
| drag | draw a stroke |
| `[` `]` | brush size down / up |
| wheel | brush size (dock open) |

The brush dock is a small floating panel: an HSV wheel with a brightness bar,
six quick-pick swatches, and a size slider with a live preview dot. Drag it by
its edge to move it. Clicks land on the dock without pulling focus off the
game; clicks anywhere else pass through exactly as before.

## Troubleshooting

| symptom | cause |
|---|---|
| `/replay/*` returns `Not Found` | `EnableReplayApi=1` missing from `game.cfg` — see Install. Also 404s while no replay is loaded |
| marks don't stay pinned to the map | no camera samples, so the projector never updates — check `/replay/render` first |
| overlay is 1 pixel wide, or `ZeroDivisionError` in `GroundPlaneProjector` | League is in exclusive fullscreen, where its window reports 2x2. Switch to Windowed |
| overlay lands on the wrong window | `find_window` takes the first title match in z-order. It looks for `League of Legends (TM) Client`, which is unique to `League of Legends.exe`; the launcher is `League of Legends`. Run `check_alignment.py` to see what won |
| hotkeys do nothing while the game has focus | Vanguard is active and the overlay is not elevated — run the terminal as administrator |
| overlay does not follow League after you move or resize it | the rect is computed once, at startup. Restart the overlay |

## Files

| | |
|---|---|
| `draw_overlay.py` | the overlay window — input, painting, hotkeys |
| `dock.py` | the floating brush dock — color wheel, swatches, size |
| `check_alignment.py` | diagnostic: which window the overlay locks onto, and whether it lands on it |
| `calculations.py` | `GroundPlaneProjector`: pixel ⇄ ground (y=0) conversion |
| `camera_feed.py` | background camera poller, timestamped and extrapolated |
| `window_helper.py` | locates League's client area, toggles native click-through |
